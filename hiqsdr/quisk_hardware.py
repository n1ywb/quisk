# This is a sample hardware file for UDP control.  Use this file for my 2010 transceiver
# described in QEX and for the improved version HiQSDR.  To turn on the extended
# features in HiQSDR, update your FPGA firmware to version 1.1 or later and use use_rx_udp = 2.

import struct, socket
import _quisk as QS

from quisk_hardware_model import Hardware as BaseHardware

DEBUG = 0

class Hardware(BaseHardware):
  def __init__(self, app, conf):
    BaseHardware.__init__(self, app, conf)
    self.use_sidetone = 1
    self.got_udp_status = ''		# status from UDP receiver
	# want_udp_status is a 14-byte string with numbers in little-endian order:
	#	[0:2]		'St'
	#	[2:6]		Rx tune phase
	#	[6:10]		Tx tune phase
	#	[10]		Tx output level 0 to 255
	#	[11]		Tx control bits:
	#		0x01	Enable CW transmit
	#		0x02	Enable all other transmit
	#		0x04	Use the HiQSDR extended IO pins not present in the 2010 QEX ver 1.0
	#		0x08	The key is down (software key)
	#	[12]	Rx control bits
	#			Second stage decimation less one, 1-39, six bits
	#	[13]	zero or firmware version number
	# The above is used for firmware  version 1.0.
	# Version 1.1 adds eight more bytes for the HiQSDR conntrol ports:
	#	[14]	X1 connector:  Preselect pins 69, 68, 65, 64; Preamp pin 63, Tx LED pin 57
	#	[15]	Attenuator pins 84, 83, 82, 81, 80
	#	[16]	More bits: AntSwitch pin 41 is 0x01
	#	[17:22] The remaining five bytes are sent as zero.
	# Version 1.2 uses the same format as 1.1, but adds the "Qs" command (see below).
	# Version 1.3 adds features needed by the new quisk_vna.py program:
	#	[17]	This one byte must be zero
	#	[18:20]	This is vna_count, the number of VNA data points; or zero for normal operation
	#	[20:22]	These two bytes mmust be zero

# The "Qs" command is a two-byte UDP packet sent to the control port.  It returns the hardware status
# as the above string, except that the string starts with "Qs" instead of "St".  Do not send the "Qs" command
# from Quisk, as it interferes with the "St" command.  The "Qs" command is meant to be used from an
# external program, such as HamLib or a logging program.

# When vna_count != 0, we are in VNA mode.  The start frequency is rx_phase, and for each point tx_phase is added
# to advance the frequency.  A zero sample is added to mark the blocks.  The samples are I and Q averaged at DC.

    self.rx_phase = 0
    self.tx_phase = 0
    self.tx_level = 0
    self.tx_control = 0
    self.rx_control = 0
    self.vna_count = 0	# VNA scan count; MUST be zero for non-VNA operation
    self.index = 0
    self.mode = None
    self.band = None
    self.HiQSDR_Connector_X1 = 0
    self.HiQSDR_Attenuator = 0
    self.HiQSDR_Bits = 0
    if conf.use_rx_udp == 2:	# Set to 2 for the HiQSDR
      self.rf_gain_labels = ('RF 0 dB', 'RF +10', 'RF -10', 'RF -20', 'RF -30')
      self.antenna_labels = ('Ant 1', 'Ant 2')
    self.firmware_version = None	# firmware version is initially unknown
    self.rx_udp_socket = None
    self.vfo_frequency = 0		# current vfo frequency
    self.tx_frequency = 0
    self.decimations = []		# supported decimation rates
    for dec in (40, 20, 10, 8, 5, 4, 2):
      self.decimations.append(dec * 64)
    if self.conf.fft_size_multiplier == 0:
      self.conf.fft_size_multiplier = 7		# Set size needed by VarDecim
  def open(self):
    self.rx_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.rx_udp_socket.setblocking(0)
    # conf.rx_udp_port is used for returning ADC samples
    # conf.rx_udp_port + 1 is used for control
    self.rx_udp_socket.connect((self.conf.rx_udp_ip, self.conf.rx_udp_port + 1))
    return QS.open_rx_udp(self.conf.rx_udp_ip, self.conf.rx_udp_port)
  def close(self):
    if self.rx_udp_socket:
      self.rx_udp_socket.close()
      self.rx_udp_socket = None
  def ReturnFrequency(self):	# Return the current tuning and VFO frequency
    return None, None		# frequencies have not changed
  def ChangeFrequency(self, tx_freq, vfo_freq, source='', band='', event=None):
    if vfo_freq != self.vfo_frequency:
      self.vfo_frequency = vfo_freq
      self.rx_phase = int(float(vfo_freq) / self.conf.rx_udp_clock * 2.0**32 + 0.5) & 0xFFFFFFFF
    if tx_freq and tx_freq > 0:
      self.tx_frequency = tx_freq
      tx = tx_freq
      self.tx_phase = int(float(tx) / self.conf.rx_udp_clock * 2.0**32 + 0.5) & 0xFFFFFFFF
    self.NewUdpStatus()
    return tx_freq, vfo_freq
  def ChangeMode(self, mode):
    # mode is a string: "USB", "AM", etc.
    self.mode = mode
    self.tx_control &= ~0x03	# Erase last two bits
    if self.vna_count:
      pass
    elif mode in ("CWL", "CWU"):
      self.tx_control |= 0x01
    elif mode in ("USB", "LSB", "AM", "FM", "DGTL"):
      self.tx_control |= 0x02
    elif mode[0:3] == 'IMD':
      self.tx_control |= 0x02
    self.SetTxLevel()
    self.NewUdpStatus()
  def ChangeBand(self, band):
    # band is a string: "60", "40", "WWV", etc.
    self.band = band
    self.HiQSDR_Connector_X1 &= ~0x0F	# Mask in the last four bits
    self.HiQSDR_Connector_X1 |= self.conf.HiQSDR_BandDict.get(band, 0) & 0x0F
    self.SetTxLevel()
    self.NewUdpStatus()
  def SetTxLevel(self):
    if self.vna_count:
      return
    elif self.mode == 'DGTL':
      self.tx_level = self.conf.digital_tx_level
    else:
      try:
        self.tx_level = self.conf.tx_level[self.band]
      except KeyError:
        self.tx_level = self.conf.tx_level[None]		# The default
  def OnButtonRfGain(self, event):
    # The HiQSDR attenuator is five bits: 2, 4, 8, 10, 20 dB
    btn = event.GetEventObject()
    n = btn.index
    self.HiQSDR_Connector_X1 &= ~0x10	# Mask in the preamp bit
    if n == 0:		# 0dB
      self.HiQSDR_Attenuator = 0
    elif n == 1:	# +10
      self.HiQSDR_Attenuator = 0
      self.HiQSDR_Connector_X1 |= 0x10
    elif n == 2:	# -10
      self.HiQSDR_Attenuator = 0x08
    elif n == 3:	# -20
      self.HiQSDR_Attenuator = 0x10
    elif n == 4:	# -30
      self.HiQSDR_Attenuator = 0x18
    else:
      self.HiQSDR_Attenuator = 0
      print 'Unknown RfGain'
    self.NewUdpStatus()
  def OnButtonPTT(self, event):
    # This feature requires firmware version 1.1 or higher
    if self.firmware_version:
      btn = event.GetEventObject()
      if btn.GetValue():		# Turn the software key bit on or off
        self.tx_control |= 0x08
      else:
        self.tx_control &= ~0x08
      self.NewUdpStatus()
  def OnButtonAntenna(self, event):
    # This feature requires extended IO
    btn = event.GetEventObject()
    if btn.index:
      self.HiQSDR_Bits |= 0x01
    else:
      self.HiQSDR_Bits &= ~0x01
    self.NewUdpStatus()
  def HeartBeat(self):
    try:	# receive the old status if any
      data = self.rx_udp_socket.recv(1024)
      if DEBUG:
        self.PrintStatus(' got ', data)
    except:
      pass
    else:
      if data[0:2] == 'St':
        self.got_udp_status = data
    if self.firmware_version is None:		# get the firmware version
      if self.want_udp_status[0:13] != self.got_udp_status[0:13]:
        try:
          self.rx_udp_socket.send(self.want_udp_status)
          if DEBUG:
            self.PrintStatus('Start', self.want_udp_status)
        except:
          pass
      else:		# We got a correct response.
        self.firmware_version = ord(self.got_udp_status[13])	# Firmware version is returned here
        if DEBUG:
          print 'Got version',  self.firmware_version
        if self.firmware_version > 0 and self.conf.use_rx_udp == 2:
          self.tx_control |= 0x04	# Use extra control bytes
        self.NewUdpStatus()
    else:
      if self.want_udp_status != self.got_udp_status:
        if DEBUG:
          self.PrintStatus('Have ', self.got_udp_status)
          self.PrintStatus(' send', self.want_udp_status)
        try:
          self.rx_udp_socket.send(self.want_udp_status)
        except:
          pass
      elif DEBUG:
        self.rx_udp_socket.send('Qs')
  def PrintStatus(self, msg, string):
    print msg, ' ',
    print string[0:2],
    for c in string[2:]:
      print "%2X" % ord(c),
    print
  def GetFirmwareVersion(self):
    return self.firmware_version
  def OnSpot(self, level):
    pass
  def VarDecimGetChoices(self):		# return text labels for the control
    clock = self.conf.rx_udp_clock
    l = []			# a list of sample rates
    for dec in self.decimations:
      l.append(str(int(float(clock) / dec / 1e3 + 0.5)))
    return l
  def VarDecimGetLabel(self):		# return a text label for the control
    return "Sample rate ksps"
  def VarDecimGetIndex(self):		# return the current index
    return self.index
  def VarDecimSet(self, index=None):		# set decimation, return sample rate
    if index is None:		# initial call to set decimation before the call to open()
      rate = self.application.vardecim_set		# May be None or from different hardware
      try:
        dec = int(float(self.conf.rx_udp_clock / rate + 0.5))
        self.index = self.decimations.index(dec)
      except:
        try:
          self.index = self.decimations.index(self.conf.rx_udp_decimation)
        except:
          self.index = 0
    else:
      self.index = index
    dec = self.decimations[self.index]
    self.rx_control = dec / 64 - 1		# Second stage decimation less one
    self.NewUdpStatus()
    return int(float(self.conf.rx_udp_clock) / dec + 0.5)
  def NewUdpStatus(self, do_tx=False):
    s = "St"
    s = s + struct.pack("<L", self.rx_phase)
    s = s + struct.pack("<L", self.tx_phase)
    s = s + chr(self.tx_level) + chr(self.tx_control)
    s = s + chr(self.rx_control)
    if self.firmware_version:	# Add the version
      s = s + chr(self.firmware_version)	# The firmware version will be returned
    else:		# firmware version 0 or None
      s = s + chr(0)	# assume version 0
    if self.firmware_version > 0:	# Add the extra bytes
      if self.tx_control & 0x04:	# Use extra HiQSDR control bytes
        s = s + chr(self.HiQSDR_Connector_X1)
        s = s + chr(self.HiQSDR_Attenuator)
        s = s + chr(self.HiQSDR_Bits)
        s = s + chr(0)
      else:
        s = s + chr(0) * 4
      s = s + struct.pack("<H", self.vna_count)
      s = s + chr(0) * 2
    self.want_udp_status = s
    if do_tx:
      try:
        self.rx_udp_socket.send(s)
      except:
        pass
  def SetVNA(self, key_down=None, vna_start=None, vna_stop=None, vna_count=None, do_tx=False):
    if key_down is None:
      pass
    elif key_down:
      self.tx_control |= 0x08
    else:
      self.tx_control &= ~0x08
    if vna_count is not None:
      self.vna_count = vna_count	# Number of scan points
    if vna_start is not None:	# Set the start and stop frequencies.  The tx_phase is the frequency delta.
      self.rx_phase = int(float(vna_start) / self.conf.rx_udp_clock * 2.0**32 + 0.5) & 0xFFFFFFFF
      self.tx_phase = int(float(vna_stop - vna_start) / self.vna_count / self.conf.rx_udp_clock * 2.0**32 + 0.5) & 0xFFFFFFFF
    self.tx_control &= ~0x03	# Erase last two bits
    self.rx_control = 40 - 1
    self.tx_level = 255
    self.NewUdpStatus(do_tx)
    start = int(float(self.rx_phase) * self.conf.rx_udp_clock / 2.0**32 + 0.5)
    stop = int(start + float(self.tx_phase) * self.vna_count * self.conf.rx_udp_clock / 2.0**32 + 0.5)
    return start, stop		# return the start and stop frequencies after integer rounding
