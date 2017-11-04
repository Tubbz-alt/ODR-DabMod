/*
   Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010 Her Majesty the
   Queen in Right of Canada (Communications Research Center Canada)

   Copyright (C) 2017
   Matthias P. Braendli, matthias.braendli@mpb.li

    http://opendigitalradio.org

DESCRIPTION:
   It is an output driver using the SoapySDR library that can output to
   many devices.
*/

/*
   This file is part of ODR-DabMod.

   ODR-DabMod is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as
   published by the Free Software Foundation, either version 3 of the
   License, or (at your option) any later version.

   ODR-DabMod is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with ODR-DabMod.  If not, see <http://www.gnu.org/licenses/>.
 */

#pragma once

#ifdef HAVE_CONFIG_H
#   include <config.h>
#endif

#ifdef HAVE_SOAPYSDR
#include <SoapySDR/Version.hpp>
#include <SoapySDR/Modules.hpp>
#include <SoapySDR/Registry.hpp>
#include <SoapySDR/Device.hpp>

#include <string>
#include <memory>

#include "output/SDR.h"
#include "ModPlugin.h"
#include "EtiReader.h"
#include "RemoteControl.h"
#include "ThreadsafeQueue.h"

namespace Output {

class Soapy : public Output::SDRDevice
{
    public:
        Soapy(SDRDeviceConfig& config);
        Soapy(const Soapy& other) = delete;
        Soapy& operator=(const Soapy& other) = delete;
        ~Soapy();

        virtual void tune(double lo_offset, double frequency) override;
        virtual double get_tx_freq(void) override;
        virtual void set_txgain(double txgain) override;
        virtual double get_txgain(void) override;
        virtual void transmit_frame(const struct FrameData& frame) override;
        virtual RunStatistics get_run_statistics(void) override;
        virtual double get_real_secs(void) override;

        virtual void set_rxgain(double rxgain) override;
        virtual double get_rxgain(void) override;
        virtual size_t receive_frame(
                complexf *buf,
                size_t num_samples,
                struct frame_timestamp& ts,
                double timeout_secs) override;

        // Return true if GPS and reference clock inputs are ok
        virtual bool is_clk_source_ok(void) override;
        virtual const char* device_name(void) override;

    private:
        SDRDeviceConfig& m_conf;
        SoapySDR::Device *m_device = nullptr;
        SoapySDR::Stream *m_tx_stream = nullptr;
        SoapySDR::Stream *m_rx_stream = nullptr;

        size_t underflows = 0;
        size_t overflows = 0;
        size_t late_packets = 0;
        size_t num_frames_modulated = 0; //TODO increment
};

} // namespace Output

#endif //HAVE_SOAPYSDR

