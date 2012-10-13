# This file supports various hardware boxes at my shack

import sys, struct, math, socket, select, thread, time, traceback, os
import serial
import _quisk as QS

DEBUG = 0

class LowPassFilter:	# Control my low pass filter box
  address = ('192.168.2.194', 0x3A00 + 39)
  # Filters are numbered 1 thru 8 for bands: 80, 15, 60, 40, 30, 20, 17, short
  lpfnum = (1, 1, 1, 1, 1, 3,	# frequency 0 thru 5 MHz
               4, 4, 5, 5, 5,	# 6 thru 10
               6, 6, 6, 6, 7,	# 11 thru 15
               7, 7, 7, 2, 2,	# 16 thru 20
               2, 2, 8, 8, 8)	# 21 thru 25; otherwise the filter is 8
  def __init__(self, app, conf):
    self.application = app	# Application instance (to provide attributes)
    self.conf = conf		# Config file module
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.socket.setblocking(0)
    self.socket.connect(self.address)
    self.have_data = None
    self.want_data = '\00'
    self.old_tx_freq = 0
    self.timer = 0
  def ChangeBand(self, band):
    pass
  def SetTxFreq(self, tx_freq):
    if not self.socket:
      return
    # Filters are numbered 1 thru 8
    if abs(self.old_tx_freq - tx_freq) < 100000:
      return	# Ignore small tuning changes
    self.old_tx_freq = tx_freq
    try:		# Look up filter number based on MHz
      num = self.lpfnum[tx_freq / 1000000]
    except IndexError:
      num = 8
    self.want_data =  chr(num)
    self.timer = 0
  def HeartBeat(self):
    if not self.socket:
      return
    try:	# The HP filter box echoes its commands
      self.have_data = self.socket.recv(50)
    except socket.error:
      pass
    except socket.timeout:
      pass
    if self.have_data != self.want_data:
      if self.timer <= 10:
        self.timer += 1
        if self.timer == 10:
          print 'Low pass filter error'
      try:
        self.socket.send(self.want_data)
      except socket.error:
        pass
      except socket.timeout:
        pass

class HighPassFilter:	# Control my high pass filter box
  address = ('192.168.2.194', 0x3A00 + 21)
  def __init__(self, app, conf):
    self.application = app	# Application instance (to provide attributes)
    self.conf = conf		# Config file module
    self.preamp = 0
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.socket.setblocking(0)
    self.socket.connect(self.address)
    self.have_data = None
    self.want_data = '\00\00\00'
    self.old_tx_freq = 0
    self.timer = 0
  def ChangeBand(self, band):
    btn = self.application.BtnRfGain
    freq = self.application.VFO + self.application.txFreq
    if self.conf.use_sdriq:
      if btn:
        if freq < 5000000:
          btn.SetLabel('RF -10', True)
        elif freq < 13000000:
          btn.SetLabel('RF 0 dB', True)
        else:
          btn.SetLabel('RF +16', True)
    elif self.conf.use_rx_udp:
      if btn:
        if freq < 5000000:
          btn.SetLabel('RF 0 dB', True)
        elif freq < 13000000:
          btn.SetLabel('RF 0 dB', True)
        else:
          btn.SetLabel('RF +16', True)
  def OnButtonRfGain(self, event):
    """Set my High Pass Filter Box preamp gain and attenuator state."""
    btn = event.GetEventObject()
    n = btn.index
    if n == 0:		# 0dB
      self.preamp = 0x00
    elif n == 1:	# +16
      self.preamp = 0x02
    elif n == 2:	# -20
      self.preamp = 0x0C
    elif n == 3:	# -10
      self.preamp = 0x04
    else:
      print 'Unknown RfGain'
    self.SetTxFreq(None)
  def SetTxFreq(self, tx_freq):
    """Set high pass filter and preamp/attenuator state"""
    # Filter cutoff in MHz: 0.0, 2.7, 3.95, 5.7, 12.6, 18.2, 22.4
    # Frequency MHz     Bits       Hex      Band
    # =============     ====       ===      ====
    #   0   to  2.70    PORTD, 0   0x01      160
    #  2.7  to  3.95    PORTB, 1   0x02       80
    #  3.95 to  5.70    PORTD, 7   0x80       60
    #  5.70 to 12.60    PORTB, 0   0x01       40, 30
    # 12.60 to 18.20    PORTD, 6   0x40       20, 17
    # 18.20 to 22.40    PORTB, 7   0x80       15
    # 22.40 to 99.99    PORTB, 6   0x40       12, 10
    # Other bits:  Preamp PORTD 0x02, Atten1 PORTD 0x04, Atten2 PORTD 0x08
    if not self.socket:
      return
    if tx_freq is None:
      tx_freq = self.old_tx_freq
    elif abs(self.old_tx_freq - tx_freq) < 100000:
      return	# Ignore small tuning changes
    self.old_tx_freq = tx_freq
    portb = portc = portd = 0
    if self.conf.use_sdriq:
      if tx_freq < 15000000:	# Turn preamp on/off
        self.preamp = 0x00
      else:
        self.preamp = 0x02
    elif self.conf.use_rx_udp:
      pass		# self.preamp is already set
    else:		# turn preamp off
      self.preamp = 0x00
    if tx_freq < 12600000:
      if tx_freq < 3950000:
        if tx_freq < 2700000:
          portd = 0x01
        else:
          portb = 0x02
      elif tx_freq < 5700000:
        portd = 0x80
      else:
        portb = 0x01
    elif tx_freq < 18200000:
      portd = 0x40
    elif tx_freq < 22400000:
      portb = 0x80
    else:
      portb = 0x40
    portd |= self.preamp
    self.want_data =  chr(portb) + chr(portc) + chr(portd)
    self.timer = 0
  def HeartBeat(self):
    if not self.socket:
      return
    try:	# The HP filter box echoes its commands
      self.have_data = self.socket.recv(50)
    except socket.error:
      pass
    except socket.timeout:
      pass
    if self.have_data != self.want_data:
      if self.timer <= 10:
        self.timer += 1
        if self.timer == 10:
          print 'High pass filter error'
      try:
        self.socket.send(self.want_data)
      except socket.error:
        pass
      except socket.timeout:
        pass

class AntennaControl:	# Control my KI8BV dipole
  AntCtrlAddress = ('192.168.2.194', 0x3A00 + 33)
  index = {'20':0, '40':1, '60':2, '80':3}
  def __init__(self, app, conf, address):
    self.application = app	# Application instance (to provide attributes)
    self.conf = conf		# Config file module
    if address:
      self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      self.socket.setblocking(0)
      self.socket.connect(address)
      self.have_data = None
      self.want_data = '\00'
      self.timer = 0
    else:
      self.socket = None
  def ChangeBand(self, band):
    if not self.socket:
      return
    self.timer = 0
    try:
      self.want_data = chr(self.index[band])
    except KeyError:
      self.want_data = chr(3)
  def SetTxFreq(self, tx_freq):
    pass
  def HeartBeat(self):
    if not self.socket:
      return
    try:	# The antenna control box echoes its commands
      self.have_data = self.socket.recv(50)
    except socket.error:
      pass
    except socket.timeout:
      pass
    if self.have_data != self.want_data:
      if self.timer <= 10:
        self.timer += 1
        if self.timer == 10:
          print 'Antenna control error'
      try:
        self.socket.send(self.want_data)
      except socket.error:
        pass
      except socket.timeout:
        pass

class AntennaTuner:		# Control an AT-200PC autotuner made by LDG
  def __init__(self, app, conf):
    self.application = app	# Application instance (to provide attributes)
    self.conf = conf		# Config file module
    self.serial = None
    self.rx_state = 0
    self.is_standby = None
    self.tx_freq = 0
    self.old_tx_freq = 0
    self.set_L = -9
    self.set_C = -9
    self.set_HiLoZ = -9
    self.tuning_F1 = 0
    self.tuning_F2 = 0
    self.tuning_diff = 0
    self.param1 = [None] * 20	# Parameters returned by the AT-200PC
    self.param2 = [None] * 20
    self.param1[5] = self.param2[5] = self.param2[6] = 0		# power and SWR
    self.param1[7] = self.param2[7] = 1		# Frequency
    self.param1[1] = self.param1[2] = 0		# Inductor, Capacitor
    self.req_swr = 50			# Requested SWR: 50 thru 56 for 1.1, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0
    self.live_update = 0		# Request live update 1 or 0
    self.antenna = 2			# Select antenna 1 or 2
    self.standby = 0			# Set standby mode 1 or 0
    self.timer = 0
    self.error = "AT-200PC serial port is not open"
    self.TunerLC_change = False
    if sys.platform == "win32":
      self.TunerLC_fname = 'C:/pub/TunerLC.txt'
    else:
      self.TunerLC_fname = '/home/jim/pub/TunerLC.txt'
  def UpdateSwr(self):
    if not self.application.bottom_widgets:
      return
    if self.error:
      self.application.bottom_widgets.UpdateText(self.error)
    else:
      power = (self.param1[5] * 256 + self.param2[5]) / 100.0
      swr = self.param2[6]	# swr code = 256 * p**2
      if power >= 2.0:
        freq = self.param1[7] * 256 + self.param2[7]
        freq = 20480000.0 / freq
        ftext = "Tx freq"
        swr = math.sqrt(swr / 256.0)
        swr = (1.0 + swr) / (1.0 - swr)
        if swr > 99.9:
          swr = 99.9
      else:
        freq = self.tuning_diff / 1000.0
        ftext = "Tune delta"
        swr = 0.0
      if self.param1[3] == 0:	# HiLoZ relay value
        t = "Zh"		# High
      else:
        t = "Zl"		# Low
      text = "Watts %.0f   SWR %.1f  %s Ind %d Cap %d   %s %.0f kHz" % (
         power, swr,  t, self.param1[1], self.param1[2], ftext, freq)
      self.application.bottom_widgets.UpdateText(text)
  def HeartBeat(self):
    if not self.serial:
      self.UpdateSwr()
      return
    self.Read()			# Receive from the AT-200PC
    # Call main application with new SWR data
    self.UpdateSwr()
    if self.error:		# Send a couple parameters, see if we get a response
      if self.req_swr - 50 != self.param1[16]:
        self.Write(chr(self.req_swr))	# Send threshold SWR
      elif self.param1[17] != 0:
        self.Write(chr(59))			# Turn off AutoTune
      else:
        self.error = ''
      return
    if self.param1[4] != self.antenna - 1:		# Check correct antenna
      self.Write(chr(9 + self.antenna))
    elif self.is_standby != self.standby:		# Check standby state
      self.Write(chr(45 - self.standby))
    elif self.param1[19] != self.live_update:	# Check live update state
      self.Write(chr(64 - self.live_update))
    elif self.set_L >= 0 and self.set_HiLoZ >= 0 and (	# Check L and Hi/Lo relay
         self.param1[1] != self.set_L or self.param1[3] != self.set_HiLoZ):
      if self.set_HiLoZ:
        self.Write(chr(65) + chr(self.set_L + 128))
      else:
        self.Write(chr(65) + chr(self.set_L))
    elif self.param1[2] != self.set_C and self.set_C >= 0:	# Set C
      self.Write(chr(66) + chr(self.set_C))
    elif self.live_update:	# If our window shows, request an update
      self.timer += 1
      if self.timer > 20:
        self.timer = 0
        self.Write(chr(40))		# Request ALLUPDATE
  def Write(self, s):		# Write a command string to the AT-200PC
    if DEBUG:
      print 'Send', ord(s[0])
    if self.serial:
      self.serial.setRTS(1)	# Wake up the AT-200PC
      time.sleep(0.003)		# Wait 3 milliseconds
      self.serial.write(s)
      self.serial.setRTS(0)
  def Read(self):	# Receive characters from the AT-200PC
    chars = self.serial.read(1024)
    for ch in chars:
      if self.rx_state == 0:	# Read first of 4 characters; must be decimal 165
        if ord(ch) == 165:
          self.rx_state = 1
      elif self.rx_state == 1:	# Read second byte
        self.rx_state = 2
        self.rx_byte1 = ord(ch)
      elif self.rx_state == 2:	# Read third byte
        self.rx_state = 3
        self.rx_byte2 = ord(ch)
      elif self.rx_state == 3:	# Read fourth byte
        self.rx_state = 0
        byte3 = ord(ch)
        byte1 = self.rx_byte1
        byte2 = self.rx_byte2
        if DEBUG:
          print 'Received', byte1, byte2, byte3
        if byte1 > 19:			# Impossible command value
          continue
        if byte1 == 1 and self.set_L < 0:	# reported inductor value
          self.set_L = byte2
        if byte1 == 2 and self.set_C < 0:	# reported capacitor value
          self.set_C = byte2
        if byte1 == 3 and self.set_HiLoZ < 0:	# reported Hi/Lo relay
          self.set_HiLoZ = byte2
        if byte1 == 13:				# Start standby
          self.is_standby = 1
        elif byte1 == 14:			# Start active
          self.is_standby = 0
        self.param1[byte1] = byte2
        self.param2[byte1] = byte3
  def OpenPort(self):
    if sys.platform == "win32":
      tty_list = ("COM7", "COM8")
    else:
      tty_list = ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2")
    for tty_name in tty_list:
      try:
        port = serial.Serial(port=tty_name, timeout=0)
      except:
        #traceback.print_exc()
        pass
      else:
        port.setRTS(0)
        time.sleep(0.1)
        for i in range(3):
          port.setRTS(1)
          time.sleep(0.003)		# Wait 3 milliseconds
          port.write(chr(41))
          port.setRTS(0)
          time.sleep(0.1)
          chars = port.read(1024)
          #print 'Got', tty_name, len(chars), str(chars)
          if chars == '?\r\n':		# Wrong port
            break
          if "\xA5\x0B\x01\x20" in chars:
            self.serial = port
            break
        if self.serial:
          break
        else:
          port.close()
  def open(self):
    self.OpenPort()
    if self.serial:
      self.error = "Waiting for AT200PC"
    # TunerLC is a list of (freq, L, C).  Use -L for Low Z, +L for High Z.
    # The first and last entry must have frequency 0 and 99999999.
    self.TunerLC = []
    fp = open(self.TunerLC_fname, 'r')
    for line in fp:
      line = line.split()
      f = int(line[0])
      l = int(line[1])
      c = int(line[2])
      self.TunerLC.append((f, l, c))
    fp.close()
  def close(self):
    if self.serial:
      self.serial.close()
      self.serial = None
    if self.TunerLC_change:
      fp = open(self.TunerLC_fname, 'w')
      for f, l, c in  self.TunerLC:
        fp.write("%9d %4d %4d\n" % (f, l, c))
      fp.close()
  def xxReqSetFreq(self, tx_freq):
    # Set relays for this frequency.  The frequency must exist in the tuner.
    if self.serial and not self.standby and tx_freq > 1500000:
      ticks = int(20480.0 / tx_freq * 1e6 + 0.5)
      self.Write(chr(67) + chr((ticks & 0xFF00) >> 8) + chr(ticks & 0xFF))
  def SetTxFreq(self, tx_freq):
    if tx_freq is None:
      self.set_C = 0
      self.set_L = 0
      self.set_HiLoZ = 0
      return
    self.tx_freq = tx_freq
    if abs(self.old_tx_freq - tx_freq) < 20000:
      d1 = tx_freq - self.tuning_F1
      d2 = tx_freq - self.tuning_F2
      if abs(d1) <= abs(d2):
        self.tuning_diff = d1
      else:
        self.tuning_diff = d2
      return	# Ignore small tuning changes
    self.old_tx_freq = tx_freq
    i1 = 0
    i2 = len(self.TunerLC) - 1
    while 1:	# binary partition
      i = (i1 + i2) / 2
      if self.TunerLC[i][0] < tx_freq:
        i1 = i
      else:
        i2 = i
      if i2 - i1 <= 1:
        break
    # The correct setting is between i1 and i2; interpolate
    F1 = self.TunerLC[i1][0]
    F2 = self.TunerLC[i2][0]
    L1 = self.TunerLC[i1][1]
    L2 = self.TunerLC[i2][1]
    C1 = self.TunerLC[i1][2]
    C2 = self.TunerLC[i2][2]
    frac = (float(tx_freq) - F1) / (F2 - F1)
    C = C1 + (C2 - C1) * frac
    self.set_C = int(C + 0.5)
    L = L1 + (L2 - L1) * frac
    if L < 0:
      L = -L
      self.set_HiLoZ = 1
    else:
      self.set_HiLoZ = 0
    self.set_L = int(L + 0.5)
    # Report the frequency difference
    self.tuning_F1 = F1
    self.tuning_F2 = F2
    d1 = tx_freq - F1
    d2 = tx_freq - F2
    if abs(d1) <= abs(d2):
      self.tuning_diff = d1
    else:
      self.tuning_diff = d2
  def ChangeBand(self, band):
    pass ##self.ReqSetFreq(self.tx_freq)
  def OnSpot(self, level):
    # level 0 == OFF, else the level 10 to 1000
    if self.serial:
      if level == 0:
        self.live_update = 0
      elif not self.live_update:
        self.live_update = 1
        self.timer = 999
  def OnAntTuner(self, text):	# One of the tuner buttons was pressed
    if self.serial:
      if text == 'Tune':
        if not self.standby:
          #self.Write(chr(5))		# Request memory tune
          self.Write(chr(6))		# Request full tune
          self.set_C = -9
          self.set_L = -9
          self.set_HiLoZ = -9
      elif text == 'Save':
        self.Write(chr(46))
        if self.set_HiLoZ == 0:		# High Z
          L = self.set_L
        else:						# Low Z
          L = -self.set_L
        for i in range(len(self.TunerLC)):	# Record new freq and L/C
          if abs(self.TunerLC[i][0] - self.tx_freq) < 1000:
            self.TunerLC[i] = (self.tx_freq, L, self.set_C)
            break
        else:
          self.TunerLC.append((self.tx_freq, L, self.set_C))
          self.TunerLC.sort()
          self.TunerLC_change = True
      elif text == 'L+':
        self.set_L += 1
      elif text == 'L-':
        self.set_L -= 1
      elif text == 'C+':
        self.set_C += 1
      elif text == 'C-':
        self.set_C -= 1
