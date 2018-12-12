#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# DPD Computation Engine standalone main file.
#
# http://www.opendigitalradio.org
# Licence: The MIT License, see notice at the end of this file

"""This Python script is the main file for ODR-DabMod's DPD Computation Engine running
in server mode.

This engine calculates and updates the parameter of the digital
predistortion module of ODR-DabMod."""

import sys
import os
import argparse
import configparser
import matplotlib
matplotlib.use('Agg')

parser = argparse.ArgumentParser(
    description="DPD Computation Engine for ODR-DabMod")
parser.add_argument('--config', default="gui-dpdce.ini", type=str,
        help='Location of configuration filename (default: gui-dpdce.ini)',
        required=False)
parser.add_argument('-s', '--status', action="store_true",
        help='Display the currently running DPD settings.')
parser.add_argument('-r', '--reset', action="store_true",
        help='Reset the DPD settings to the defaults, and set digital gain to 0.01')

cli_args = parser.parse_args()
allconfig = configparser.ConfigParser()
allconfig.read(cli_args.config)
config = allconfig['dpdce']

# removed options:
# txgain, rxgain, digital_gain, target_median, iterations, lut, enable-txgain-agc, plot, measure

control_port = config.getint('control_port')
dpd_port = config.getint('dpd_port')
rc_port = config.getint('rc_port')
samplerate = config.getint('samplerate')
samps = config.getint('samps')
coef_file = config['coef_file']
log_folder = config['log_folder']

import logging
import datetime

save_logs = False

# Simple usage scenarios don't need to clutter /tmp
if save_logs:
    dt = datetime.datetime.now().isoformat()
    logging_path = '/tmp/dpd_{}'.format(dt).replace('.', '_').replace(':', '-')
    print("Logs and plots written to {}".format(logging_path))
    os.makedirs(logging_path)
    logging.basicConfig(format='%(asctime)s - %(module)s - %(levelname)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        filename='{}/dpd.log'.format(logging_path),
                        filemode='w',
                        level=logging.DEBUG)
    # also log up to INFO to console
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(asctime)s - %(module)s - %(levelname)s - %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)
else:
    dt = datetime.datetime.now().isoformat()
    logging.basicConfig(format='%(asctime)s - %(module)s - %(levelname)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO)
    logging_path = ""

logging.info("DPDCE starting up");

import socket
from lib import yamlrpc
import numpy as np
import traceback
from threading import Thread, Lock
from queue import Queue
from dpd.Model import Poly
import dpd.Heuristics as Heuristics
from dpd.Measure import Measure
from dpd.ExtractStatistic import ExtractStatistic
from dpd.Adapt import Adapt, dpddata_to_str
from dpd.RX_Agc import Agc
from dpd.Symbol_align import Symbol_align
from dpd.GlobalConfig import GlobalConfig
from dpd.MER import MER
from dpd.Measure_Shoulders import Measure_Shoulders

c = GlobalConfig(samplerate, logging_path)
symbol_align = Symbol_align(c)
mer = MER(c)
meas_shoulders = Measure_Shoulders(c)
meas = Measure(c, samplerate, dpd_port, samps)
extStat = ExtractStatistic(c)
adapt = Adapt(rc_port, coef_file, logging_path)

model = Poly(c)

# Do not touch settings on startup
tx_gain = adapt.get_txgain()
rx_gain = adapt.get_rxgain()
digital_gain = adapt.get_digital_gain()
dpddata = adapt.get_predistorter()

logging.info("ODR-DabMod currently running with TXGain {}, RXGain {}, digital gain {} and {}".format(
    tx_gain, rx_gain, digital_gain, dpddata_to_str(dpddata)))

if cli_args.status:
    sys.exit(0)

if cli_args.reset:
    adapt.set_digital_gain(0.01)
    adapt.set_rxgain(0)
    adapt.set_predistorter(model.get_dpd_data())
    logging.info("DPD Settings were reset to default values.")
    sys.exit(0)

cmd_socket = yamlrpc.Socket(bind_port=control_port)

# The following is accessed by both threads and need to be locked
settings = {
        'rx_gain': rx_gain,
        'tx_gain': tx_gain,
        'digital_gain': digital_gain,
        'dpddata': dpddata,
        }
results = {
        'tx_median': 0,
        'rx_median': 0,
        'state': 'Idle',
        'stateprogress': 0, # in percent
        'summary': ['DPD has not been calibrated yet'],
        }
lock = Lock()
command_queue = Queue(maxsize=1)

# Automatic Gain Control for the RX gain
agc = Agc(meas, adapt, c)

def engine_worker():
    try:
        while True:
            cmd = command_queue.get()

            if cmd == "quit":
                break
            elif cmd == "calibrate":
                with lock:
                    results['state'] = 'RX Gain Calibration'
                    results['stateprogress'] = 0

                summary = []
                N_ITER = 5
                for i in range(N_ITER):
                    agc_success, agc_summary = agc.run()
                    summary = ["calibration run {}:".format(i)] + agc_summary.split("\n")

                    with lock:
                        results['stateprogress'] = int((i + 1) * 100/N_ITER)

                    if not agc_success:
                        break

                txframe_aligned, tx_ts, rxframe_aligned, rx_ts, rx_median, tx_median = meas.get_samples()

                with lock:
                    settings['rx_gain'] = adapt.get_rxgain()
                    settings['digital_gain'] = adapt.get_digital_gain()
                    results['tx_median'] = float(tx_median)
                    results['rx_median'] = float(rx_median)
                    results['state'] = 'Idle'
                    results['stateprogress'] = 0
                    results['summary'] = ["Calibration was done:"] + summary

    finally:
        with lock:
            results['state'] = 'Terminated'
            results['stateprogress'] = 0


engine = Thread(target=engine_worker)
engine.start()

try:
    while True:
        try:
            addr, msg_id, method, params = cmd_socket.receive_request()
        except ValueError as e:
            logging.warning('YAML-RPC request error: {}'.format(e))
            continue
        except TimeoutError:
            continue
        except KeyboardInterrupt:
            logging.info('Caught KeyboardInterrupt')
            break
        except:
            logging.error('YAML-RPC unknown error')
            break

        if method == 'trigger_run':
            logging.info('YAML-RPC request : {}'.format(method))
            command_queue.put('trigger_run')
        elif method == 'reset':
            logging.info('YAML-RPC request : {}'.format(method))
            command_queue.put('reset')
        elif method == 'set_setting':
            logging.info('YAML-RPC request : {} -> {}'.format(method, params))
            # params == {'setting': ..., 'value': ...}
            pass
        elif method == 'get_settings':
            with lock:
                cmd_socket.send_success_response(addr, msg_id, settings)
        elif method == 'get_results':
            with lock:
                cmd_socket.send_success_response(addr, msg_id, results)
        elif method == 'calibrate':
            logging.info('YAML-RPC request : {}'.format(method))
            command_queue.put('calibrate')
        else:
            cmd_socket.send_error_response(addr, msg_id, "request not understood")
finally:
    command_queue.put('quit')
    logging.info('Waiting for DPDCE to stop')
    engine.join()

# Make code below unreachable
sys.exit(0)

def measure_once():
    txframe_aligned, tx_ts, rxframe_aligned, rx_ts, rx_median, tx_median = meas.get_samples()

    print("TX signal median {}".format(np.median(np.abs(txframe_aligned))))
    print("RX signal median {}".format(rx_median))

    tx, rx, phase_diff, n_per_bin = extStat.extract(txframe_aligned, rxframe_aligned)

    off = symbol_align.calc_offset(txframe_aligned)
    print("off {}".format(off))
    tx_mer = mer.calc_mer(txframe_aligned[off:off + c.T_U], debug_name='TX')
    print("tx_mer {}".format(tx_mer))
    rx_mer = mer.calc_mer(rxframe_aligned[off:off + c.T_U], debug_name='RX')
    print("rx_mer {}".format(rx_mer))

    mse = np.mean(np.abs((txframe_aligned - rxframe_aligned) ** 2))
    print("mse {}".format(mse))

    digital_gain = adapt.get_digital_gain()
    print("digital_gain {}".format(digital_gain))

    #rx_shoulder_tuple = meas_shoulders.average_shoulders(rxframe_aligned)
    #tx_shoulder_tuple = meas_shoulders.average_shoulders(txframe_aligned)

state = 'report'
i = 0
n_meas = None
num_iter = 10
while i < num_iter:
    try:
        # Measure
        if state == 'measure':
            # Get Samples and check gain
            txframe_aligned, tx_ts, rxframe_aligned, rx_ts, rx_median, tx_median = meas.get_samples()
            # TODO Check TX median

            # Extract usable data from measurement
            tx, rx, phase_diff, n_per_bin = extStat.extract(txframe_aligned, rxframe_aligned)

            n_meas = Heuristics.get_n_meas(i)
            if extStat.n_meas >= n_meas:  # Use as many measurements nr of runs
                state = 'model'
            else:
                state = 'measure'

        # Model
        elif state == 'model':
            # Calculate new model parameters and delete old measurements
            if any(x is None for x in [tx, rx, phase_diff]):
                logging.error("No data to calculate model")
                state = 'measure'
                continue

            model.train(tx, rx, phase_diff, lr=Heuristics.get_learning_rate(i))
            dpddata = model.get_dpd_data()
            extStat = ExtractStatistic(c)
            state = 'adapt'

        # Adapt
        elif state == 'adapt':
            adapt.set_predistorter(dpddata)
            state = 'report'

        # Report
        elif state == 'report':
            try:
                txframe_aligned, tx_ts, rxframe_aligned, rx_ts, rx_median, tx_median = meas.get_samples()

                # Store all settings for pre-distortion, tx and rx
                adapt.dump()

                # Collect logging data
                off = symbol_align.calc_offset(txframe_aligned)
                tx_mer = mer.calc_mer(txframe_aligned[off:off + c.T_U], debug_name='TX')
                rx_mer = mer.calc_mer(rxframe_aligned[off:off + c.T_U], debug_name='RX')
                mse = np.mean(np.abs((txframe_aligned - rxframe_aligned) ** 2))
                tx_gain = adapt.get_txgain()
                rx_gain = adapt.get_rxgain()
                digital_gain = adapt.get_digital_gain()
                tx_median = np.median(np.abs(txframe_aligned))
                rx_shoulder_tuple = meas_shoulders.average_shoulders(rxframe_aligned)
                tx_shoulder_tuple = meas_shoulders.average_shoulders(txframe_aligned)

                lr = Heuristics.get_learning_rate(i)

                # Generic logging
                logging.info(list((name, eval(name)) for name in
                                  ['i', 'tx_mer', 'tx_shoulder_tuple', 'rx_mer',
                                   'rx_shoulder_tuple', 'mse', 'tx_gain',
                                   'digital_gain', 'rx_gain', 'rx_median',
                                   'tx_median', 'lr', 'n_meas']))

                # Model specific logging
                if dpddata[0] == 'poly':
                    coefs_am = dpddata[1]
                    coefs_pm = dpddata[2]
                    logging.info('It {}: coefs_am {}'.
                                 format(i, coefs_am))
                    logging.info('It {}: coefs_pm {}'.
                                 format(i, coefs_pm))
                elif dpddata[0] == 'lut':
                    scalefactor = dpddata[1]
                    lut = dpddata[2]
                    logging.info('It {}: LUT scalefactor {}, LUT {}'.
                                 format(i, scalefactor, lut))
            except:
                logging.error('Iteration {}: Report failed.'.format(i))
                logging.error(traceback.format_exc())
            i += 1
            state = 'measure'

    except:
        logging.error('Iteration {} failed.'.format(i))
        logging.error(traceback.format_exc())
        i += 1
        state = 'measure'

# The MIT License (MIT)
#
# Copyright (c) 2017 Andreas Steger
# Copyright (c) 2018 Matthias P. Braendli
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.