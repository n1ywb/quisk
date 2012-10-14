#! /usr/bin/env python

# All QUISK software is Copyright (C) 2006-2011 by James C. Ahlstrom.
# This free software is licensed for use under the GNU General Public
# License (GPL), see http://www.opensource.org.
# Note that there is NO WARRANTY AT ALL.  USE AT YOUR OWN RISK!!

"""The main program for Quisk, a software defined radio.

Usage:  python quisk.py [-c | --config config_file_path]
This can also be installed as a package and run as quisk.main().
"""

# Change to the directory of quisk.py.  This is necessary to import Quisk packages
# and to load other extension modules that link against _quisk.so.  It also helps to
# find ./__init__.py and ./help.html.
import sys, os
os.chdir(os.path.normpath(os.path.dirname(__file__)))
if sys.path[0] != "'.'":		# Make sure the current working directory is on path
  sys.path.insert(0, '.')

import wx, wx.html, wx.lib.buttons, wx.lib.stattext, wx.lib.colourdb
import math, cmath, time, traceback, string
import threading, pickle, webbrowser
if sys.version_info[0] == 3:	# Python3
  from xmlrpc.client import ServerProxy
else:				# Python version 2.x
  from xmlrpclib import ServerProxy
import _quisk as QS
from types import *
from quisk_widgets import *
from filters import Filters

# Fldigi XML-RPC control opens a local socket.  If socket.setdefaulttimeout() is not
# called, the timeout on Linux is zero (1 msec) and on Windows is 2 seconds.  So we
# call it to insure consistent behavior.
import socket
socket.setdefaulttimeout(0.005)

# Command line parsing: be able to specify the config file.
from optparse import OptionParser
parser = OptionParser()
parser.add_option('-c', '--config', dest='config_file_path',
		help='Specify the configuration file path')
parser.add_option('', '--config2', dest='config_file_path2', default='',
		help='Specify a second configuration file to read after the first')
argv_options = parser.parse_args()[0]
ConfigPath = argv_options.config_file_path	# Get config file path
ConfigPath2 = argv_options.config_file_path2
if not ConfigPath:	# Use default path
  if sys.platform == 'win32':
    path = os.getenv('HOMEDRIVE', '') + os.getenv('HOMEPATH', '')
    for dir in ("Documents", "My Documents", "Eigene Dateien", "Documenti"):
      ConfigPath = os.path.join(path, dir)
      if os.path.isdir(ConfigPath):
        break
    else:
      ConfigPath = os.path.join(path, "My Documents")
    ConfigPath = os.path.join(ConfigPath, "quisk_conf.py")
    if not os.path.isfile(ConfigPath):	# See if the user has a config file
      try:
        import shutil	# Try to create an initial default config file
        shutil.copyfile('quisk_conf_win.py', ConfigPath)
      except:
        pass
  else:
    ConfigPath = os.path.expanduser('~/.quisk_conf.py')

# These FFT sizes have multiple small factors, and are prefered for efficiency:
fftPreferedSizes = (416, 448, 480, 512, 576, 640, 672, 704, 768, 800, 832,
864, 896, 960, 1024, 1056, 1120, 1152, 1248, 1280, 1344, 1408, 1440, 1536,
1568, 1600, 1664, 1728, 1760, 1792, 1920, 2016, 2048, 2080, 2112, 2240, 2304,
2400, 2464, 2496, 2560, 2592, 2688, 2816, 2880, 2912)

def round(x):	# round float to nearest integer
  if x >= 0:
    return int(x + 0.5)
  else:
    return - int(-x + 0.5)

class Timer:
  """Debug: measure and print times every ptime seconds.

  Call with msg == '' to start timer, then with a msg to record the time.
  """
  def __init__(self, ptime = 1.0):
    self.ptime = ptime		# frequency to print in seconds
    self.time0 = 0			# time zero; measure from this time
    self.time_print = 0		# last time data was printed
    self.timers = {}		# one timer for each msg
    self.names = []			# ordered list of msg
    self.heading = 1		# print heading on first use
  def __call__(self, msg):
    tm = time.time()
    if msg:
      if not self.time0:		# Not recording data
        return
      if self.timers.has_key(msg):
        count, average, highest = self.timers[msg]
      else:
        self.names.append(msg)
        count = 0
        average = highest = 0.0
      count += 1
      delta = tm - self.time0
      average += delta
      if highest < delta:
        highest = delta
      self.timers[msg] = (count, average, highest)
      if tm - self.time_print > self.ptime:	# time to print results
        self.time0 = 0		# end data recording, wait for reset
        self.time_print = tm
        if self.heading:
          self.heading = 0
          print "count, msg, avg, max (msec)"
        print "%4d" % count,
        for msg in self.names:		# keep names in order
          count, average, highest = self.timers[msg]
          if not count:
            continue
          average /= count
          print "  %s  %7.3f  %7.3f" % (msg, average * 1e3, highest * 1e3),
          self.timers[msg] = (0, 0.0, 0.0)
        print
    else:	# reset the time to zero
      self.time0 = tm		# Start timer
      if not self.time_print:
        self.time_print = tm

## T = Timer()		# Make a timer instance

class HamlibHandler:
  """This class is created for each connection to the server.  It services requests from each client"""
  SingleLetters = {		# convert single-letter commands to long commands
    '_':'info',
    'f':'freq',
    'i':'split_freq',
    'm':'mode',
    's':'split_vfo',
    't':'ptt',
    'v':'vfo',
    }
# I don't understand the need for dump_state, nor what it means.
# A possible response to the "dump_state" request:
  dump1 = """ 2
2
2
150000.000000 1500000000.000000 0x1ff -1 -1 0x10000003 0x3
0 0 0 0 0 0 0
0 0 0 0 0 0 0
0x1ff 1
0x1ff 0
0 0
0x1e 2400
0x2 500
0x1 8000
0x1 2400
0x20 15000
0x20 8000
0x40 230000
0 0
9990
9990
10000
0
10 
10 20 30 
0x3effffff
0x3effffff
0x7fffffff
0x7fffffff
0x7fffffff
0x7fffffff
"""

# Another possible response to the "dump_state" request:
  dump2 = """ 0
2
2
150000.000000 30000000.000000  0x900af -1 -1 0x10 000003 0x3
0 0 0 0 0 0 0
150000.000000 30000000.000000  0x900af -1 -1 0x10 000003 0x3
0 0 0 0 0 0 0
0 0
0 0
0
0
0
0


0x0
0x0
0x0
0x0
0x0
0
"""
  def __init__(self, app, sock, address):
    self.app = app		# Reference back to the "hardware"
    self.sock = sock
    sock.settimeout(0.0)
    self.address = address
    self.received = ''
    h = self.Handlers = {}
    h[''] = self.ErrProtocol
    h['dump_state']	= self.DumpState
    h['get_freq']	= self.GetFreq
    h['set_freq']	= self.SetFreq
    h['get_info']	= self.GetInfo
    h['get_mode']	= self.GetMode
    h['set_mode']	= self.SetMode
    h['get_vfo']	= self.GetVfo
    h['get_ptt']	= self.GetPtt
    h['set_ptt']	= self.SetPtt
    h['get_split_freq']	= self.GetSplitFreq
    h['set_split_freq']	= self.SetSplitFreq
    h['get_split_vfo']	= self.GetSplitVfo
    h['set_split_vfo']	= self.SetSplitVfo
  def Send(self, text):
    """Send text back to the client."""
    try:
      self.sock.sendall(text)
    except socket.error:
      self.sock.close()
      self.sock = None
  def Reply(self, *args):	# args is name, value, name, value, ..., int
    """Create a string reply of name, value pairs, and an ending integer code."""
    if self.extended:			# Use extended format
      t = "%s:" % self.cmd		# Extended format echoes the command and parameters
      for param in self.params:
        t = "%s %s" % (t, param)
      t += self.extended
      for i in range(0, len(args) - 1, 2):
        t = "%s%s: %s%c" % (t, args[i], args[i+1], self.extended)
      t += "RPRT %d\n" % args[-1]
    elif len(args) > 1:		# Use simple format
      t = ''
      for i in range(1, len(args) - 1, 2):
        t = "%s%s\n" % (t, args[i])
    else:		# No names; just the required integer code
      t = "RPRT %d\n" % args[0]
    # print 'Reply', t
    self.Send(t)
  def ErrParam(self):		# Invalid parameter
    self.Reply(-1)
  def UnImplemented(self):	# Command not implemented
    self.Reply(-4)
  def ErrProtocol(self):	# Protocol error
    self.Reply(-8)
  def Process(self):
    """This is the main processing loop, and is called frequently.  It reads and satisfies requests."""
    if not self.sock:
      return 0
    try:	# Read any data from the socket
      text = self.sock.recv(1024)
    except socket.timeout:	# This does not work
      pass
    except socket.error:	# Nothing to read
      pass
    else:					# We got some characters
      self.received += text
    if '\n' in self.received:	# A complete command ending with newline is available
      cmd, self.received = self.received.split('\n', 1)	# Split off the command, save any further characters
    else:
      return 1
    cmd = cmd.strip()		# Here is our command
    # print 'Get', cmd
    if not cmd:			# ??? Indicates a closed connection?
      # print 'empty command'
      self.sock.close()
      self.sock = None
      return 0
    # Parse the command and call the appropriate handler
    if cmd[0] == '+':			# rigctld Extended Response Protocol
      self.extended = '\n'
      cmd = cmd[1:].strip()
    elif cmd[0] in ';|,':		# rigctld Extended Response Protocol
      self.extended = cmd[0]
      cmd = cmd[1:].strip()
    else:
      self.extended = None
    if cmd[0:1] == '\\':		# long form command starting with backslash
      args = cmd[1:].split()
      self.cmd = args[0]
      self.params = args[1:]
      self.Handlers.get(self.cmd, self.UnImplemented)()
    else:						# single-letter command
      self.params = cmd[1:].strip()
      cmd = cmd[0:1]
      if cmd in 'Qq':	# Quit command
        return 0
      try:
        t = self.SingleLetters[cmd.lower()]
      except KeyError:
        self.UnImplemented()
      else:
        if cmd in string.uppercase:
          self.cmd = 'set_' + t
        else:
          self.cmd = 'get_' + t
        self.Handlers.get(self.cmd, self.UnImplemented)()
    return 1
  # These are the handlers for each request
  def DumpState(self):
    self.Send(self.dump2)
  def GetFreq(self):
    self.Reply('Frequency', self.app.rxFreq + self.app.VFO, 0)
  def SetFreq(self):
    try:
      freq = float(self.params)
      self.Reply(0)
    except:
      self.ErrParam()
    else:
      freq = int(freq + 0.5)
      self.app.ChangeRxTxFrequency(freq, None)
  def GetSplitFreq(self):
    self.Reply('TX Frequency', self.app.txFreq + self.app.VFO, 0)
  def SetSplitFreq(self):
    try:
      freq = float(self.params)
      self.Reply(0)
    except:
      self.ErrParam()
    else:
      freq = int(freq + 0.5)
      self.app.ChangeRxTxFrequency(None, freq)
  def GetSplitVfo(self):
    # I am not sure if "VFO" is a suitable response
    if self.app.split_rxtx:
      self.Reply('Split', 1, 'TX VFO', 'VFO', 0)
    else:
      self.Reply('Split', 0, 'TX VFO', 'VFO', 0)
  def SetSplitVfo(self):
    # Currently (Aug 2012) hamlib fails to send the "split" parameter, so this fails
    try:
      split, vfo = self.params.split()
      split = int(split)
      self.Reply(0)
    except:
      # traceback.print_exc()
      self.ErrParam()
    else:
      self.app.splitButton.SetValue(split, True)
  def GetInfo(self):
    self.Reply("Info", self.app.main_frame.GetTitle(), 0)
  def GetMode(self):
    mode = self.app.mode
    if mode == 'CWU':
      mode = 'CW'
    elif mode == 'CWL':		# Is this what CWR means?
      mode = 'CWR'
    elif mode == 'DGTL':
      mode = 'USB'
    self.Reply('Mode', mode, 'Passband', self.app.filter_bandwidth, 0)
  def SetMode(self):
    try:
      mode, bw = self.params.split()
      bw = int(float(bw) + 0.5)
    except:
      self.ErrParam()
      return
    if mode in ('USB', 'LSB', 'AM', 'FM', 'DGTL'):
      self.Reply(0)
    elif mode == 'CW':
      mode = 'CWU'
      self.Reply(0)
    elif mode == 'CWR':
      mode = 'CWL'
      self.Reply(0)
    else:
      self.ErrParam()
      return
    self.app.OnBtnMode(None, mode)		# Set mode
    if bw <= 0:		# use default bandwidth
      return
    # Choose button closest to requested bandwidth
    buttons = self.app.filterButns.GetButtons()
    Lab = buttons[0].GetLabel()
    diff = abs(int(Lab) - bw)
    for i in range(1, len(buttons) - 1):
      label = buttons[i].GetLabel()
      df = abs(int(label) - bw)
      if df < diff:
        Lab = label
        diff = df
    self.app.OnBtnFilter(None, int(Lab))
  def GetVfo(self):
    self.Reply('VFO', "VFO", 0)		# The type of VFO we have
  def GetPtt(self):
    if QS.is_key_down():
      self.Reply('PTT', 1, 0)
    else:
      self.Reply('PTT', 0, 0)
  def SetPtt(self):
    if not self.app.pttButton:
      self.UnImplemented()
      return
    try:
      ptt = int(self.params)
      self.Reply(0)
    except:
      self.ErrParam()
    else:
      self.app.pttButton.SetValue(ptt, True)

class SoundThread(threading.Thread):
  """Create a second (non-GUI) thread to read, process and play sound."""
  def __init__(self):
    self.do_init = 1
    threading.Thread.__init__(self)
    self.doQuit = threading.Event()
    self.doQuit.clear()
  def run(self):
    """Read, process, play sound; then notify the GUI thread to check for FFT data."""
    if self.do_init:	# Open sound using this thread
      self.do_init = 0
      QS.start_sound()
      wx.CallAfter(application.PostStartup)
    while not self.doQuit.isSet():
      QS.read_sound()
      wx.CallAfter(application.OnReadSound)
    QS.close_sound()
  def stop(self):
    """Set a flag to indicate that the sound thread should end."""
    self.doQuit.set()

class ConfigScreen(wx.Panel):
  """Display a notebook with status and configuration data"""
  def __init__(self, parent, width, fft_size):
    self.y_scale = 0
    self.y_zero = 0
    wx.Panel.__init__(self, parent)
    notebook = wx.Notebook(self)
    notebook.SetBackgroundColour(conf.color_graph)
    self.SetBackgroundColour(conf.color_config2)
    font = wx.Font(12, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    notebook.SetFont(font)
    sizer = wx.BoxSizer()
    sizer.Add(notebook, 1, wx.EXPAND)
    self.SetSizer(sizer)
    # create the page windows
    self.status = ConfigStatus(notebook, width, fft_size)
    notebook.AddPage(self.status, "Status")
    self.config = ConfigConfig(notebook, width)
    notebook.AddPage(self.config, "Config")
    self.sound = ConfigSound(notebook, width)
    notebook.AddPage(self.sound, "Sound")
  def ChangeYscale(self, y_scale):
    pass
  def ChangeYzero(self, y_zero):
    pass
  def OnIdle(self, event):
    pass
  def SetTxFreq(self, tx_freq, rx_freq):
    pass
  def OnGraphData(self, data=None):
    self.status.OnGraphData(data)
  def InitBitmap(self):		# Initial construction of bitmap
    self.status.InitBitmap()

class ConfigStatus(wx.Panel):
  """Display the status screen."""
  def __init__(self, parent, width, fft_size):
    wx.Panel.__init__(self, parent)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.width = width
    self.fft_size = fft_size
    self.interupts = 0
    self.read_error = -1
    self.write_error = -1
    self.underrun_error = -1
    self.fft_error = -1
    self.latencyCapt = -1
    self.latencyPlay = -1
    self.y_scale = 0
    self.y_zero = 0
    self.rate_min = -1
    self.rate_max = -1
    self.chan_min = -1
    self.chan_max = -1
    self.mic_max_display = 0
    self.err_msg = "No response"
    self.msg1 = ""
    self.font = wx.Font(14, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    self.SetFont(self.font)
    charx = self.charx = self.GetCharWidth()
    chary = self.chary = self.GetCharHeight()
    self.dy = chary		# line spacing
    self.rjustify1 = (0, 1, 0)
    self.tabstops1 = [0] * 3
    self.tabstops1[0] = x = charx
    self.tabstops1[1] = x = x + self.GetTextExtent("FFT number of errors 1234567890")[0]
    self.tabstops1[2] = x = x + self.GetTextExtent("XXXX")[0]
    self.rjustify2 = (0, 0, 1, 1, 1)
    self.tabstops2 = []
  def MakeTabstops(self):
    luse = lname = 0
    for use, name, rate, latency, errors in QS.sound_errors():
      w, h = self.GetTextExtent(use)
      luse = max(luse, w)
      w, h = self.GetTextExtent(name)
      lname = max(lname, w)
    if luse == 0:
      return
    charx = self.charx
    self.tabstops2 = [0] * 5
    self.tabstops2[0] = x = charx
    self.tabstops2[1] = x = x + luse + charx * 6
    self.tabstops2[2] = x = x + lname + self.GetTextExtent("Sample rateXXXXXX")[0]
    self.tabstops2[3] = x = x + charx * 12
    self.tabstops2[4] = x = x + charx * 12
  def OnPaint(self, event):
    # Make and blit variable data
    self.MakeBitmap()
    dc = wx.PaintDC(self)
    dc.Blit(0, 0, self.mem_width, self.mem_height, self.mem_dc, 0, 0)
  def MakeRow2(self, *args):
    for col in range(len(args)):
      t = args[col]
      if t is None:
        continue
      t = str(t)
      x = self.tabstops[col]
      if self.rjustify[col]:
        w, h = self.mem_dc.GetTextExtent(t)
        x -= w
      if "Error" in t and t != "Errors":
        self.mem_dc.SetTextForeground('Red')
        self.mem_dc.DrawText(t, x, self.mem_y)
        self.mem_dc.SetTextForeground(conf.color_graphlabels)
      else:
        self.mem_dc.DrawText(t, x, self.mem_y)
    self.mem_y += self.dy
  def InitBitmap(self):		# Initial construction of bitmap
    self.mem_height = application.screen_height
    self.mem_width = application.screen_width
    self.bitmap = wx.EmptyBitmap(self.mem_width, self.mem_height)
    self.mem_dc = wx.MemoryDC()
    self.mem_rect = wx.Rect(0, 0, self.mem_width, self.mem_height)
    self.mem_dc.SelectObject(self.bitmap)
    br = wx.Brush(conf.color_graph)
    self.mem_dc.SetBackground(br)
    self.mem_dc.SetFont(self.font)
    self.mem_dc.SetTextForeground(conf.color_graphlabels)
    self.mem_dc.Clear()
  def MakeBitmap(self):
    self.mem_dc.Clear()
    self.mem_y = self.charx
    self.tabstops = self.tabstops1
    self.rjustify = self.rjustify1
    if conf.config_file_exists:
      cfile = "Configuration file:  %s" % conf.config_file_path
    else:
      cfile = "Error: Configuration file not found %s" % conf.config_file_path
    if conf.microphone_name:
      level = "%3.0f" % self.mic_max_display
    else:
      level = "None"
    if self.err_msg:
      err_msg = self.err_msg
    else:
      err_msg = None
    self.MakeRow2("Sample interrupts", self.interupts, cfile)
    self.MakeRow2("Microphone level dB", level, application.config_text)
    self.MakeRow2("FFT number of points", self.fft_size, err_msg)
    self.MakeRow2("FFT number of errors", self.fft_error)
    self.mem_y += self.dy
    if not self.tabstops2:
      return
    self.tabstops = self.tabstops2
    self.rjustify = self.rjustify2
    self.font.SetUnderlined(True)
    self.mem_dc.SetFont(self.font)
    self.MakeRow2("Device", "Name", "Sample rate", "Latency", "Errors")
    self.font.SetUnderlined(False)
    self.mem_dc.SetFont(self.font)
    self.mem_y += self.dy * 3 / 10
    if conf.use_sdriq:
      self.MakeRow2("Capture radio samples", "SDR-IQ", application.sample_rate, self.latencyCapt, self.read_error)
    elif conf.use_rx_udp:
      self.MakeRow2("Capture radio samples", "UDP", application.sample_rate, self.latencyCapt, self.read_error)
    for use, name, rate, latency, errors in QS.sound_errors():
      self.MakeRow2(use, name, rate, latency, errors)
  def OnGraphData(self, data=None):
    if not self.tabstops2:      # Must wait for sound to start
      self.MakeTabstops()
    (self.rate_min, self.rate_max, sample_rate, self.chan_min, self.chan_max,
         self.msg1, self.unused, self.err_msg,
         self.read_error, self.write_error, self.underrun_error,
         self.latencyCapt, self.latencyPlay, self.interupts, self.fft_error, self.mic_max_display,
         self.data_poll_usec
	 ) = QS.get_state()
    self.mic_max_display = 20.0 * math.log10((self.mic_max_display + 1) / 32767.0)
    self.RefreshRect(self.mem_rect)

class ConfigConfig(wx.Panel):
  def __init__(self, parent, width):
    wx.Panel.__init__(self, parent)
    self.width = width
    self.SetBackgroundColour(conf.color_graph)
    self.font = wx.Font(14, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    self.SetFont(self.font)
    self.charx = charx = self.GetCharWidth()
    self.chary = chary = self.GetCharHeight()
    self.dy = self.chary
    self.rx_phase = None
    self.text_audio = "Record audio to WAV file "
    self.text_samples = "Record samples to WAV file "
    # Make controls
    tab0 = charx * 4
    # Receive phase
    rx = wx.StaticText(self, -1, "Adjust receive amplitude and phase")
    tx = wx.StaticText(self, -1, "Adjust transmit amplitude and phase")
    x1, y1 = tx.GetSizeTuple()
    self.rx_phase = ctrl = wx.Button(self, -1, "Rx Phase...")
    self.Bind(wx.EVT_BUTTON, self.OnBtnPhase, ctrl)
    if not conf.name_of_sound_capt:
      ctrl.Enable(0)
    x2, y2 = ctrl.GetSizeTuple()
    tab1 = tab0 + x1 + charx * 2
    tab2 = tab1 + x2 + charx * 8
    self.y = y2 + self.chary
    self.dy = y2 * 12 / 10
    self.offset = (y2 - y1) / 2
    rx.SetPosition((tab0, self.y))
    ctrl.SetPosition((tab1, self.y - self.offset))
    # File for recording speaker audio
    b = wx.Button(self, -1, "File...", pos=(tab2, self.y - self.offset))
    self.Bind(wx.EVT_BUTTON, self.OnBtnFileAudio, b)
    x3, y3 = b.GetSizeTuple()
    tab3 = tab2 + x3 + charx
    self.static_audio = wx.StaticText(self, -1, self.text_audio + 'none', pos=(tab3, self.y))
    self.y += self.dy
    # Transmit phase
    self.tx_phase = ctrl = wx.Button(self, -1, "Tx Phase...")
    self.Bind(wx.EVT_BUTTON, self.OnBtnPhase, ctrl)
    if not conf.name_of_mic_play:
      ctrl.Enable(0)
    tx.SetPosition((tab0, self.y))
    ctrl.SetPosition((tab1, self.y - self.offset))
    # File for recording samples
    b = wx.Button(self, -1, "File...", pos=(tab2, self.y - self.offset))
    self.Bind(wx.EVT_BUTTON, self.OnBtnFileSamples, b)
    self.static_samples = wx.StaticText(self, -1, self.text_samples + 'none', pos=(tab3, self.y))
    self.y += self.dy
    # Choice (combo) box for decimation
    lst = Hardware.VarDecimGetChoices()
    if lst:
      txt = Hardware.VarDecimGetLabel()
      index = Hardware.VarDecimGetIndex()
    else:
      txt = "Variable decimation"
      lst = ["None"]
      index = 0
    t = wx.StaticText(self, -1, txt)
    ctrl = wx.Choice(self, -1, choices=lst, size=(x2, y2))
    if lst:
      self.Bind(wx.EVT_CHOICE, application.OnBtnDecimation, ctrl)
      ctrl.SetSelection(index)
    t.SetPosition((tab0, self.y))
    ctrl.SetPosition((tab1, self.y - self.offset))
    self.y += self.dy
  def OnBtnPhase(self, event):
    btn = event.GetEventObject()
    if btn.GetLabel()[0:2] == 'Tx':
      rx_tx = 'tx'
    else:
      rx_tx = 'rx'
    application.screenBtnGroup.SetLabel('Graph', do_cmd=True)
    if application.w_phase:
      application.w_phase.Raise()
    else:
      application.w_phase = QAdjustPhase(self, self.width, rx_tx)
  def OnBtnFileAudio(self, event):
    dlg = wx.FileDialog(self, 'Choose WAV file', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
      wildcard="Wave files (*.wav)|*.wav")
    if dlg.ShowModal() == wx.ID_OK:
      path = dlg.GetPath()
      if path[-4:].lower() != '.wav':
        path = path + '.wav'
      QS.set_file_record(0, path)
      application.btn_file_record.Enable()
    else:
      path = 'none'
      QS.set_file_record(0, '')
    self.static_audio.SetLabel(self.text_audio + path)
    dlg.Destroy()
  def OnBtnFileSamples(self, event):
    dlg = wx.FileDialog(self, 'Choose WAV file', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
      wildcard="Wave files (*.wav)|*.wav")
    if dlg.ShowModal() == wx.ID_OK:
      path = dlg.GetPath()
      if path[-4:].lower() != '.wav':
        path = path + '.wav'
      QS.set_file_record(1, path)
      application.btn_file_record.Enable()
    else:
      path = 'none'
      QS.set_file_record(1, '')
    self.static_samples.SetLabel(self.text_samples + path)
    dlg.Destroy()

class ConfigSound(wx.Panel):
  """Display the available sound devices."""
  def __init__(self, parent, width):
    wx.Panel.__init__(self, parent)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.width = width
    self.dev_capt, self.dev_play = QS.sound_devices()
    self.SetBackgroundColour(conf.color_graph)
    self.font = wx.Font(14, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    self.SetFont(self.font)
    self.charx = self.GetCharWidth()
    self.chary = self.GetCharHeight()
    self.dy = self.chary
  def OnPaint(self, event):
    dc = wx.PaintDC(self)
    dc.SetFont(self.font)
    dc.SetTextForeground(conf.color_graphlabels)
    x0 = self.charx
    self.y = self.chary / 3
    dc.DrawText("Available devices for capture:", x0, self.y)
    self.y += self.dy
    for name in self.dev_capt:
      dc.DrawText('    ' + name, x0, self.y)
      self.y += self.dy
    dc.DrawText("Available devices for playback:", x0, self.y)
    self.y += self.dy
    for name in self.dev_play:
      dc.DrawText('    ' + name, x0, self.y)
      self.y += self.dy

class GraphDisplay(wx.Window):
  """Display the FFT graph within the graph screen."""
  def __init__(self, parent, x, y, graph_width, height, chary):
    wx.Window.__init__(self, parent,
       pos = (x, y),
       size = (graph_width, height),
       style = wx.NO_BORDER)
    self.parent = parent
    self.chary = chary
    self.graph_width = graph_width
    self.line = [(0, 0), (1,1)]		# initial fake graph data
    self.SetBackgroundColour(conf.color_graph)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.Bind(wx.EVT_LEFT_DOWN, parent.OnLeftDown)
    self.Bind(wx.EVT_RIGHT_DOWN, parent.OnRightDown)
    self.Bind(wx.EVT_LEFT_UP, parent.OnLeftUp)
    self.Bind(wx.EVT_MOTION, parent.OnMotion)
    self.Bind(wx.EVT_MOUSEWHEEL, parent.OnWheel)
    self.tune_tx = graph_width / 2	# Current X position of the Tx tuning line
    self.tune_rx = 0				# Current X position of Rx tuning line or zero
    self.scale = 20				# pixels per 10 dB
    self.peak_hold = 9999		# time constant for holding peak value
    self.height = 10
    self.y_min = 1000
    self.y_max = 0
    self.max_height = application.screen_height
    self.tuningPenTx = wx.Pen(conf.color_txline, 1)
    self.tuningPenRx = wx.Pen(conf.color_rxline, 1)
    self.backgroundPen = wx.Pen(self.GetBackgroundColour(), 1)
    self.backgroundBrush = wx.Brush(self.GetBackgroundColour())
    self.horizPen = wx.Pen(conf.color_gl, 1, wx.SOLID)
    if sys.platform == 'win32':
      self.Bind(wx.EVT_ENTER_WINDOW, self.OnEnter)
    # This code displays the filter bandwidth on the graph screen.  It is based on code
    # provided by Terry Fox, WB4JFI.  Thanks Terry!
    self.fltr_disp_size = 1
    self.fltr_disp_tune = 0
    bitmap = wx.EmptyBitmap(graph_width, self.max_height)
    self.fltr_disp_tx_dc = wx.MemoryDC()
    self.fltr_disp_tx_dc.SelectObject(bitmap)
    br = wx.Brush(conf.color_bandwidth, wx.SOLID)
    self.fltr_disp_tx_dc.SetBackground(br)
    self.fltr_disp_tx_dc.SetPen(self.tuningPenTx)
    self.fltr_disp_tx_dc.DrawLine(0, 0, 0, self.max_height)
    bitmap = wx.EmptyBitmap(graph_width, self.max_height)
    self.fltr_disp_rx_dc = wx.MemoryDC()
    self.fltr_disp_rx_dc.SelectObject(bitmap)
    br = wx.Brush(conf.color_bandwidth, wx.SOLID)
    self.fltr_disp_rx_dc.SetBackground(br)
    self.fltr_disp_rx_dc.SetPen(self.tuningPenRx)
    self.fltr_disp_rx_dc.DrawLine(0, 0, 0, self.max_height)
  def OnEnter(self, event):
    if not application.w_phase:
      self.SetFocus()	# Set focus so we get mouse wheel events
  def OnPaint(self, event):
    #print 'GraphDisplay', self.GetUpdateRegion().GetBox()
    dc = wx.PaintDC(self)
    # Blit the tuning line and filter display to the screen
    dc.Blit(self.tune_tx - self.fltr_disp_tune, 0, self.fltr_disp_size, self.max_height, self.fltr_disp_tx_dc, 0, 0)
    if self.tune_rx:
      dc.Blit(self.tune_rx - self.fltr_disp_tune, 0, self.fltr_disp_size, self.max_height, self.fltr_disp_rx_dc, 0, 0)
    dc.SetPen(wx.Pen(conf.color_graphline, 1))
    dc.DrawLines(self.line)
    dc.SetPen(self.horizPen)
    for y in self.parent.y_ticks:
      dc.DrawLine(0, y, self.graph_width, y)	# y line
  def SetHeight(self, height):
    self.height = height
    self.SetSize((self.graph_width, height))
  def OnGraphData(self, data):
    x = 0
    for y in data:	# y is in dB, -130 to 0
      y = self.zeroDB - int(y * self.scale / 10.0 + 0.5)
      try:
        y0 = self.line[x][1]
      except IndexError:
        self.line.append([x, y])
      else:
        if y > y0:
          y = min(y, y0 + self.peak_hold)
        self.line[x] = [x, y]
      x = x + 1
    self.Refresh()
  def XXOnGraphData(self, data):
    line = []
    x = 0
    y_min = 1000
    y_max = 0
    for y in data:	# y is in dB, -130 to 0
      y = self.zeroDB - int(y * self.scale / 10.0 + 0.5)
      if y > y_max:
        y_max = y
      if y < y_min:
        y_min = y
      line.append((x, y))
      x = x + 1
    ymax = max(y_max, self.y_max)
    ymin = min(y_min, self.y_min)
    rect = wx.Rect(0, ymin, 1000, ymax - ymin)
    self.y_min = y_min
    self.y_max = y_max
    self.line = line
    self.Refresh() #rect=rect)
  def UpdateFilterDisplay(self, size, tune):	# WB4JFI ADD - Update filter display
    self.fltr_disp_size = size
    self.fltr_disp_tune = tune
    self.fltr_disp_tx_dc.Clear()
    self.fltr_disp_tx_dc.DrawLine(tune, 0, tune, self.max_height)
    self.fltr_disp_rx_dc.Clear()
    self.fltr_disp_rx_dc.DrawLine(tune, 0, tune, self.max_height)
  def SetTuningLine(self, tune_tx, tune_rx):
    dc = wx.ClientDC(self)
    dc.SetPen(self.backgroundPen)
    dc.SetBrush(self.backgroundBrush)
    sz = self.fltr_disp_size
    xa = self.tune_tx - self.fltr_disp_tune
    dc.DrawRectangle(xa, 0, sz, self.max_height)
    xb = xa + sz
    if self.tune_rx:
      x = self.tune_rx - self.fltr_disp_tune
      dc.DrawRectangle(x, 0, sz, self.max_height)
      xa = min(xa, x)
      xb = max(xb, x + sz)
    x = tune_tx - self.fltr_disp_tune
    dc.Blit(x, 0, sz, self.max_height, self.fltr_disp_tx_dc, 0, 0)
    xa = min(xa, x)
    xb = max(xb, x + sz)
    if tune_rx:
      x = tune_rx - self.fltr_disp_tune
      dc.Blit(x, 0, sz, self.max_height, self.fltr_disp_rx_dc, 0, 0)
      xa = min(xa, x)
      xb = max(xb, x + sz)
    dc.SetPen(wx.Pen(conf.color_graphticks,1))
    dc.DrawLines(self.line[xa:xb])
    dc.SetPen(self.horizPen)
    for y in self.parent.y_ticks:
      dc.DrawLine(xa, y, xb, y)	# y line
    self.tune_tx = tune_tx
    self.tune_rx = tune_rx

class GraphScreen(wx.Window):
  """Display the graph screen X and Y axis, and create a graph display."""
  def __init__(self, parent, data_width, graph_width, in_splitter=0):
    wx.Window.__init__(self, parent, pos = (0, 0))
    self.in_splitter = in_splitter	# Are we in the top of a splitter window?
    if in_splitter:
      self.y_scale = conf.waterfall_graph_y_scale
      self.y_zero = conf.waterfall_graph_y_zero
    else:
      self.y_scale = conf.graph_y_scale
      self.y_zero = conf.graph_y_zero
    self.y_ticks = []
    self.VFO = 0
    self.WheelMod = 50		# Round frequency when using mouse wheel
    self.txFreq = 0
    self.sample_rate = application.sample_rate
    self.zoom = 1.0
    self.zoom_deltaf = 0
    self.data_width = data_width
    self.graph_width = graph_width
    self.doResize = False
    self.pen_tick = wx.Pen(conf.color_graphticks, 1)
    self.pen_label = wx.Pen(conf.color_graphlabels, 1)
    self.font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    self.SetFont(self.font)
    w = self.GetCharWidth() * 14 / 10
    h = self.GetCharHeight()
    self.charx = w
    self.chary = h
    self.tick = max(2, h * 3 / 10)
    self.originX = w * 5
    self.offsetY = h + self.tick
    self.width = self.originX + self.graph_width + self.tick + self.charx * 2
    self.height = application.screen_height * 3 / 10
    self.x0 = self.originX + self.graph_width / 2		# center of graph
    self.tuningX = self.x0
    self.originY = 10
    self.zeroDB = 10	# y location of zero dB; may be above the top of the graph
    self.scale = 10
    self.SetSize((self.width, self.height))
    self.SetSizeHints(self.width, 1, self.width)
    self.SetBackgroundColour(conf.color_graph)
    self.Bind(wx.EVT_SIZE, self.OnSize)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
    self.Bind(wx.EVT_RIGHT_DOWN, self.OnRightDown)
    self.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
    self.Bind(wx.EVT_MOTION, self.OnMotion)
    self.Bind(wx.EVT_MOUSEWHEEL, self.OnWheel)
    self.MakeDisplay()
  def MakeDisplay(self):
    self.display = GraphDisplay(self, self.originX, 0, self.graph_width, 5, self.chary)
    self.display.zeroDB = self.zeroDB
  def OnPaint(self, event):
    dc = wx.PaintDC(self)
    dc.SetFont(self.font)
    dc.SetTextForeground(conf.color_graphlabels)
    if self.in_splitter:
      self.MakeYTicks(dc)
    else:
      self.MakeYTicks(dc)
      self.MakeXTicks(dc)
  def OnIdle(self, event):
    if self.doResize:
      self.ResizeGraph()
  def OnSize(self, event):
    self.doResize = True
    event.Skip()
  def ResizeGraph(self):
    """Change the height of the graph.

    Changing the width interactively is not allowed because the FFT size is fixed.
    Call after changing the zero or scale to recalculate the X and Y axis marks.
    """
    w, h = self.GetClientSize()
    if self.in_splitter:	# Splitter window has no X axis scale
      self.height = h
      self.originY = h
    else:
      self.height = h - self.chary		# Leave space for X scale
      self.originY = self.height - self.offsetY
    self.MakeYScale()
    self.display.SetHeight(self.originY)
    self.display.scale = self.scale
    self.doResize = False
    self.Refresh()
  def ChangeYscale(self, y_scale):
    self.y_scale = y_scale
    self.doResize = True
  def ChangeYzero(self, y_zero):
    self.y_zero = y_zero
    self.doResize = True
  def ChangeZoom(self, zoom, deltaf):
    self.zoom = zoom
    self.zoom_deltaf = deltaf
    self.doResize = True
  def MakeYScale(self):
    chary = self.chary
    scale = (self.originY - chary)  * 10 / (self.y_scale + 20)	# Number of pixels per 10 dB
    scale = max(1, scale)
    q = (self.originY - chary ) / scale / 2
    zeroDB = chary + q * scale - self.y_zero * scale / 10
    if zeroDB > chary:
      zeroDB = chary
    self.scale = scale
    self.zeroDB = zeroDB
    self.display.zeroDB = self.zeroDB
    QS.record_graph(self.originX, self.zeroDB, self.scale)
  def MakeYTicks(self, dc):
    chary = self.chary
    x1 = self.originX - self.tick * 3	# left of tick mark
    x2 = self.originX - 1		# x location of y axis
    x3 = self.originX + self.graph_width	# end of graph data
    dc.SetPen(self.pen_tick)
    dc.DrawLine(x2, 0, x2, self.originY + 1)	# y axis
    y = self.zeroDB
    del self.y_ticks[:]
    for i in range(0, -99999, -10):
      if y >= chary / 2:
        dc.SetPen(self.pen_tick)
        dc.DrawLine(x1, y, x2, y)	# y tick
        self.y_ticks.append(y)
        t = `i`
        w, h = dc.GetTextExtent(t)
        # draw text on Y axis
        if y + h / 2 <= self.originY:	
          dc.DrawText(`i`, x1 - w, y - h / 2)
        elif h < self.scale:
          dc.DrawText(`i`, x1 - w, self.originY - h)
      y = y + self.scale
      if y >= self.originY:
        break
  def MakeXTicks(self, dc):
    sample_rate = int(self.sample_rate * self.zoom)
    VFO = self.VFO + self.zoom_deltaf
    originY = self.originY
    x3 = self.originX + self.graph_width	# end of fft data
    charx , z = dc.GetTextExtent('-30000XX')
    tick0 = self.tick
    tick1 = tick0 * 2
    tick2 = tick0 * 3
    # Draw the X axis
    dc.SetPen(self.pen_tick)
    dc.DrawLine(self.originX, originY, x3, originY)
    # Draw the band plan colors below the X axis
    x = self.originX
    f = float(x - self.x0) * sample_rate / self.data_width
    c = None
    y = originY + 1
    for freq, color in conf.BandPlan:
      freq -= VFO
      if f < freq:
        xend = int(self.x0 + float(freq) * self.data_width / sample_rate + 0.5)
        if c is not None:
          dc.SetPen(wx.TRANSPARENT_PEN)
          dc.SetBrush(wx.Brush(c))
          dc.DrawRectangle(x, y, min(x3, xend) - x, tick0)  # x axis
        if xend >= x3:
          break
        x = xend
        f = freq
      c = color
    stick =  1000		# small tick in Hertz
    mtick =  5000		# medium tick
    ltick = 10000		# large tick
    # check the width of the frequency label versus frequency span
    df = charx * sample_rate / self.data_width
    if df < 1000:
      tfreq = 1000		# tick frequency for labels
    elif df < 5000:
      tfreq = 5000		# tick frequency for labels
    elif df < 10000:
      tfreq = 10000
    elif df < 20000:
      tfreq = 20000
    elif df < 50000:
      tfreq = 50000
      stick =  5000
      mtick = 10000
      ltick = 50000
    else:
      tfreq = 100000
      stick =  5000
      mtick = 10000
      ltick = 50000
    # Draw the X axis ticks and frequency in kHz
    dc.SetPen(self.pen_tick)
    freq1 = VFO - sample_rate / 2
    freq1 = (freq1 / stick) * stick
    freq2 = freq1 + sample_rate + stick + 1
    y_end = 0
    for f in range (freq1, freq2, stick):
      x = self.x0 + int(float(f - VFO) / sample_rate * self.data_width)
      if self.originX <= x <= x3:
        if f % ltick is 0:		# large tick
          dc.DrawLine(x, originY, x, originY + tick2)
        elif f % mtick is 0:	# medium tick
          dc.DrawLine(x, originY, x, originY + tick1)
        else:					# small tick
          dc.DrawLine(x, originY, x, originY + tick0)
        if f % tfreq is 0:		# place frequency label
          t = str(f/1000)
          w, h = dc.GetTextExtent(t)
          dc.DrawText(t, x - w / 2, originY + tick2)
          y_end = originY + tick2 + h
    if y_end:		# mark the center of the display
      dc.DrawLine(self.x0, y_end, self.x0, application.screen_height)
  def OnGraphData(self, data):
    i1 = (self.data_width - self.graph_width) / 2
    i2 = i1 + self.graph_width
    self.display.OnGraphData(data[i1:i2])
  def SetVFO(self, vfo):
    self.VFO = vfo
    self.doResize = True
  def SetTxFreq(self, tx_freq, rx_freq):
    sample_rate = int(self.sample_rate * self.zoom)
    self.txFreq = tx_freq
    tx_x = self.x0 + int(float(tx_freq - self.zoom_deltaf) / sample_rate * self.data_width)
    self.tuningX = tx_x
    rx_x = self.x0 + int(float(rx_freq - self.zoom_deltaf) / sample_rate * self.data_width)
    if abs(tx_x - rx_x) < 2:		# Do not display Rx line for small frequency offset
      self.display.SetTuningLine(tx_x - self.originX, 0)
    else:
      self.display.SetTuningLine(tx_x - self.originX, rx_x - self.originX)
  def GetMousePosition(self, event):
    """For mouse clicks in our display, translate to our screen coordinates."""
    mouse_x, mouse_y = event.GetPositionTuple()
    win = event.GetEventObject()
    if win is not self:
      x, y = win.GetPositionTuple()
      mouse_x += x
      mouse_y += y
    return mouse_x, mouse_y
  def FreqRound(self, tune, vfo):
    if conf.freq_spacing:
      freq = tune + vfo
      n = int(freq) - conf.freq_base
      if n >= 0:
        n = (n + conf.freq_spacing / 2) / conf.freq_spacing
      else:
        n = - ( - n + conf.freq_spacing / 2) / conf.freq_spacing
      freq = conf.freq_base + n * conf.freq_spacing
      return freq - vfo
    else:
      return tune
  def OnRightDown(self, event):
    sample_rate = int(self.sample_rate * self.zoom)
    VFO = self.VFO + self.zoom_deltaf
    mouse_x, mouse_y = self.GetMousePosition(event)
    freq = float(mouse_x - self.x0) * sample_rate / self.data_width
    freq = int(freq)
    if VFO > 0:
      vfo = VFO + freq - self.zoom_deltaf
      if sample_rate > 40000:
        vfo = (vfo + 5000) / 10000 * 10000	# round to even number
      elif sample_rate > 5000:
        vfo = (vfo + 500) / 1000 * 1000
      else:
        vfo = (vfo + 50) / 100 * 100
      tune = freq + VFO - vfo
      tune = self.FreqRound(tune, vfo)
      self.ChangeHwFrequency(tune, vfo, 'MouseBtn3', event)
  def OnLeftDown(self, event):
    sample_rate = int(self.sample_rate * self.zoom)
    mouse_x, mouse_y = self.GetMousePosition(event)
    self.mouse_x = mouse_x
    x = mouse_x - self.originX
    if self.display.tune_rx and abs(x - self.display.tune_tx) > abs(x - self.display.tune_rx):
      self.mouse_is_rx = True
    else:
      self.mouse_is_rx = False
    if mouse_y < self.originY:		# click above X axis
      freq = float(mouse_x - self.x0) * sample_rate / self.data_width + self.zoom_deltaf
      freq = int(freq)
      if self.mouse_is_rx:
        application.rxFreq = freq
        application.screen.SetTxFreq(self.txFreq, freq)
        QS.set_tune(freq + application.ritFreq, self.txFreq)
      else:
        freq = self.FreqRound(freq, self.VFO)
        self.ChangeHwFrequency(freq, self.VFO, 'MouseBtn1', event)
    self.CaptureMouse()
  def OnLeftUp(self, event):
    if self.HasCapture():
      self.ReleaseMouse()
      freq = self.FreqRound(self.txFreq, self.VFO)
      if freq != self.txFreq:
        self.ChangeHwFrequency(freq, self.VFO, 'MouseMotion', event)
  def OnMotion(self, event):
    sample_rate = int(self.sample_rate * self.zoom)
    if event.Dragging() and event.LeftIsDown():
      mouse_x, mouse_y = self.GetMousePosition(event)
      if conf.mouse_tune_method:		# Mouse motion changes the VFO frequency
        x = (mouse_x - self.mouse_x)	# Thanks to VK6JBL
        self.mouse_x = mouse_x
        freq = x * sample_rate / self.data_width
        freq = int(freq)
        self.ChangeHwFrequency(self.txFreq, self.VFO - freq, 'MouseMotion', event)
      else:		# Mouse motion changes the tuning frequency
        # Frequency changes more rapidly for higher mouse Y position
        speed = max(10, self.originY - mouse_y) / float(self.originY)
        x = (mouse_x - self.mouse_x)
        self.mouse_x = mouse_x
        freq = speed * x * sample_rate / self.data_width
        freq = int(freq)
        if self.mouse_is_rx:	# Mouse motion changes the receive frequency
          application.rxFreq += freq
          application.screen.SetTxFreq(self.txFreq, application.rxFreq)
          QS.set_tune(application.rxFreq + application.ritFreq, self.txFreq)
        else:					# Mouse motion changes the transmit frequency
          self.ChangeHwFrequency(self.txFreq + freq, self.VFO, 'MouseMotion', event)
  def OnWheel(self, event):
    if conf.freq_spacing:
      wm = conf.freq_spacing
    else:
      wm = self.WheelMod		# Round frequency when using mouse wheel
    mouse_x, mouse_y = self.GetMousePosition(event)
    x = mouse_x - self.originX
    if self.display.tune_rx and abs(x - self.display.tune_tx) > abs(x - self.display.tune_rx):
      freq = application.rxFreq + self.VFO + wm * event.GetWheelRotation() / event.GetWheelDelta()
      if conf.freq_spacing:
        freq = self.FreqRound(freq, 0)
      elif freq >= 0:
        freq = freq / wm * wm
      else:		# freq can be negative when the VFO is zero
        freq = - (- freq / wm * wm)
      tune = freq - self.VFO
      application.rxFreq = tune
      application.screen.SetTxFreq(self.txFreq, tune)
      QS.set_tune(tune + application.ritFreq, self.txFreq)
    else:
      freq = self.txFreq + self.VFO + wm * event.GetWheelRotation() / event.GetWheelDelta()
      if conf.freq_spacing:
        freq = self.FreqRound(freq, 0)
      elif freq >= 0:
        freq = freq / wm * wm
      else:		# freq can be negative when the VFO is zero
        freq = - (- freq / wm * wm)
      tune = freq - self.VFO
      self.ChangeHwFrequency(tune, self.VFO, 'MouseWheel', event)
  def ChangeHwFrequency(self, tune, vfo, source, event):
    application.ChangeHwFrequency(tune, vfo, source, event)
  def PeakHold(self, name):
    if name == 'GraphP1':
      self.display.peak_hold = int(self.display.scale * conf.graph_peak_hold_1)
    elif name == 'GraphP2':
      self.display.peak_hold = int(self.display.scale * conf.graph_peak_hold_2)
    else:
      self.display.peak_hold = 9999
    if self.display.peak_hold < 1:
      self.display.peak_hold = 1

class WaterfallDisplay(wx.Window):
  """Create a waterfall display within the waterfall screen."""
  def __init__(self, parent, x, y, graph_width, height, margin):
    wx.Window.__init__(self, parent,
       pos = (x, y),
       size = (graph_width, height),
       style = wx.NO_BORDER)
    self.parent = parent
    self.graph_width = graph_width
    self.margin = margin
    self.height = 10
    self.zoom = 1.0
    self.zoom_deltaf = 0
    self.sample_rate = application.sample_rate
    self.SetBackgroundColour('Black')
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.Bind(wx.EVT_LEFT_DOWN, parent.OnLeftDown)
    self.Bind(wx.EVT_RIGHT_DOWN, parent.OnRightDown)
    self.Bind(wx.EVT_LEFT_UP, parent.OnLeftUp)
    self.Bind(wx.EVT_MOTION, parent.OnMotion)
    self.Bind(wx.EVT_MOUSEWHEEL, parent.OnWheel)
    self.tune_tx = graph_width / 2	# Current X position of the Tx tuning line
    self.tune_rx = 0				# Current X position of Rx tuning line or zero
    self.tuningPen = wx.Pen('White', 3)
    self.marginPen = wx.Pen(conf.color_graph, 1)
    # Size of top faster scroll region is (top_key + 2) * (top_key - 1) / 2
    self.top_key = 8
    self.top_size = (self.top_key + 2) * (self.top_key - 1) / 2
    # Make the palette
    pal2 = conf.waterfallPalette
    red = []
    green = []
    blue = []
    n = 0
    for i in range(256):
      if i > pal2[n+1][0]:
         n = n + 1
      red.append((i - pal2[n][0]) *
       (long)(pal2[n+1][1] - pal2[n][1]) /
       (long)(pal2[n+1][0] - pal2[n][0]) + pal2[n][1])
      green.append((i - pal2[n][0]) *
       (long)(pal2[n+1][2] - pal2[n][2]) /
       (long)(pal2[n+1][0] - pal2[n][0]) + pal2[n][2])
      blue.append((i - pal2[n][0]) *
       (long)(pal2[n+1][3] - pal2[n][3]) /
       (long)(pal2[n+1][0] - pal2[n][0]) + pal2[n][3])
    self.red = red
    self.green = green
    self.blue = blue
    bmp = wx.EmptyBitmap(0, 0)
    bmp.x_origin = 0
    self.bitmaps = [bmp] * application.screen_height
    if sys.platform == 'win32':
      self.Bind(wx.EVT_ENTER_WINDOW, self.OnEnter)
  def OnEnter(self, event):
    if not application.w_phase:
      self.SetFocus()	# Set focus so we get mouse wheel events
  def OnPaint(self, event):
    sample_rate = int(self.sample_rate * self.zoom)
    dc = wx.BufferedPaintDC(self)
    dc.SetTextForeground(conf.color_graphlabels)
    dc.SetBackground(wx.Brush('Black'))
    dc.Clear()
    y = 0
    dc.SetPen(self.marginPen)
    x_origin = int(float(self.VFO) / sample_rate * self.data_width + 0.5)
    for i in range(0, self.margin):
      dc.DrawLine(0, y, self.graph_width, y)
      y += 1
    index = 0
    if conf.waterfall_scroll_mode:	# Draw the first few lines multiple times
      for i in range(self.top_key, 1, -1):
        b = self.bitmaps[index]
        x = b.x_origin - x_origin
        for j in range(0, i):
          dc.DrawBitmap(b, x, y)
          y += 1
        index += 1
    while y < self.height:
      b = self.bitmaps[index]
      x = b.x_origin - x_origin
      dc.DrawBitmap(b, x, y)
      y += 1
      index += 1
    dc.SetPen(self.tuningPen)
    dc.SetLogicalFunction(wx.XOR)
    dc.DrawLine(self.tune_tx, 0, self.tune_tx, self.height)
    if self.tune_rx:
      dc.DrawLine(self.tune_rx, 0, self.tune_rx, self.height)
  def SetHeight(self, height):
    self.height = height
    self.SetSize((self.graph_width, height))
  def OnGraphData(self, data, y_zero, y_scale):
    sample_rate = int(self.sample_rate * self.zoom)
    #T('graph start')
    row = ''		# Make a new row of pixels for a one-line image
    for x in data:	# x is -130 to 0, or so (dB)
      l = int((x + y_zero / 3 + 100) * y_scale / 10)
      l = max(l, 0)
      l = min(l, 255)
      row = row + "%c%c%c" % (chr(self.red[l]), chr(self.green[l]), chr(self.blue[l]))
    #T('graph string')
    bmp = wx.BitmapFromBuffer(len(row) / 3, 1, row)
    bmp.x_origin = int(float(self.VFO) / sample_rate * self.data_width + 0.5)
    self.bitmaps.insert(0, bmp)
    del self.bitmaps[-1]
    #self.ScrollWindow(0, 1, None)
    #self.Refresh(False, (0, 0, self.graph_width, self.top_size + self.margin))
    self.Refresh(False)
    #T('graph end')
  def SetTuningLine(self, tune_tx, tune_rx):
    dc = wx.ClientDC(self)
    dc.SetPen(self.tuningPen)
    dc.SetLogicalFunction(wx.XOR)
    dc.DrawLine(self.tune_tx, 0, self.tune_tx, self.height)
    if self.tune_rx:
      dc.DrawLine(self.tune_rx, 0, self.tune_rx, self.height)
    dc.DrawLine(tune_tx, 0, tune_tx, self.height)
    if tune_rx:
      dc.DrawLine(tune_rx, 0, tune_rx, self.height)
    self.tune_tx = tune_tx
    self.tune_rx = tune_rx
  def ChangeZoom(self, zoom, deltaf):
    self.zoom = zoom
    self.zoom_deltaf = deltaf

class WaterfallScreen(wx.SplitterWindow):
  """Create a splitter window with a graph screen and a waterfall screen"""
  def __init__(self, frame, width, data_width, graph_width):
    self.y_scale = conf.waterfall_y_scale
    self.y_zero = conf.waterfall_y_zero
    wx.SplitterWindow.__init__(self, frame)
    self.SetSizeHints(width, -1, width)
    self.SetMinimumPaneSize(1)
    self.SetSize((width, conf.waterfall_graph_size + 100))	# be able to set sash size
    self.pane1 = GraphScreen(self, data_width, graph_width, 1)
    self.pane2 = WaterfallPane(self, data_width, graph_width)
    self.SplitHorizontally(self.pane1, self.pane2, conf.waterfall_graph_size)
  def OnIdle(self, event):
    self.pane1.OnIdle(event)
    self.pane2.OnIdle(event)
  def SetTxFreq(self, tx_freq, rx_freq):
    self.pane1.SetTxFreq(tx_freq, rx_freq)
    self.pane2.SetTxFreq(tx_freq, rx_freq)
  def SetVFO(self, vfo):
    self.pane1.SetVFO(vfo)
    self.pane2.SetVFO(vfo) 
  def ChangeYscale(self, y_scale):		# Test if the shift key is down
    if wx.GetKeyState(wx.WXK_SHIFT):	# Set graph screen
      self.pane1.ChangeYscale(y_scale)
    else:			# Set waterfall screen
      self.y_scale = y_scale
      self.pane2.ChangeYscale(y_scale)
  def ChangeYzero(self, y_zero):		# Test if the shift key is down
    if wx.GetKeyState(wx.WXK_SHIFT):	# Set graph screen
      self.pane1.ChangeYzero(y_zero)
    else:			# Set waterfall screen
      self.y_zero = y_zero
      self.pane2.ChangeYzero(y_zero)
  def OnGraphData(self, data):
    self.pane1.OnGraphData(data)
    self.pane2.OnGraphData(data)

class WaterfallPane(GraphScreen):
  """Create a waterfall screen with an X axis and a waterfall display."""
  def __init__(self, frame, data_width, graph_width):
    GraphScreen.__init__(self, frame, data_width, graph_width)
    self.y_scale = conf.waterfall_y_scale
    self.y_zero = conf.waterfall_y_zero
    self.oldVFO = self.VFO
  def MakeDisplay(self):
    self.display = WaterfallDisplay(self, self.originX, 0, self.graph_width, 5, self.chary)
    self.display.VFO = self.VFO
    self.display.data_width = self.data_width
  def SetVFO(self, vfo):
    GraphScreen.SetVFO(self, vfo)
    self.display.VFO = vfo
    if self.oldVFO != vfo:
      self.oldVFO = vfo
      self.Refresh()
  def MakeYTicks(self, dc):
    pass
  def ChangeYscale(self, y_scale):
    self.y_scale = y_scale
  def ChangeYzero(self, y_zero):
    self.y_zero = y_zero
  def OnGraphData(self, data):
    i1 = (self.data_width - self.graph_width) / 2
    i2 = i1 + self.graph_width
    self.display.OnGraphData(data[i1:i2], self.y_zero, self.y_scale)

class ScopeScreen(wx.Window):
  """Create an oscilloscope screen (mostly used for debug)."""
  def __init__(self, parent, width, data_width, graph_width):
    wx.Window.__init__(self, parent, pos = (0, 0),
       size=(width, -1), style = wx.NO_BORDER)
    self.SetBackgroundColour(conf.color_graph)
    self.font = wx.Font(16, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    self.SetFont(self.font)
    self.Bind(wx.EVT_SIZE, self.OnSize)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    self.horizPen = wx.Pen(conf.color_gl, 1, wx.SOLID)
    self.y_scale = conf.scope_y_scale
    self.y_zero = conf.scope_y_zero
    self.running = 1
    self.doResize = False
    self.width = width
    self.height = 100
    self.originY = self.height / 2
    self.data_width = data_width
    self.graph_width = graph_width
    w = self.charx = self.GetCharWidth()
    h = self.chary = self.GetCharHeight()
    tick = max(2, h * 3 / 10)
    self.originX = w * 3
    self.width = self.originX + self.graph_width + tick + self.charx * 2
    self.line = [(0,0), (1,1)]	# initial fake graph data
    self.fpout = None #open("jim96.txt", "w")
  def OnIdle(self, event):
    if self.doResize:
      self.ResizeGraph()
  def OnSize(self, event):
    self.doResize = True
    event.Skip()
  def ResizeGraph(self, event=None):
    # Change the height of the graph.  Changing the width interactively is not allowed.
    w, h = self.GetClientSize()
    self.height = h
    self.originY = h / 2
    self.doResize = False
    self.Refresh()
  def OnPaint(self, event):
    dc = wx.PaintDC(self)
    dc.SetFont(self.font)
    dc.SetTextForeground(conf.color_graphlabels)
    self.MakeYTicks(dc)
    self.MakeXTicks(dc)
    self.MakeText(dc)
    dc.SetPen(wx.Pen(conf.color_graphline, 1))
    dc.DrawLines(self.line)
  def MakeYTicks(self, dc):
    chary = self.chary
    originX = self.originX
    x3 = self.x3 = originX + self.graph_width	# end of graph data
    dc.SetPen(wx.Pen(conf.color_graphticks,1))
    dc.DrawLine(originX, 0, originX, self.originY * 3)	# y axis
    # Find the size of the Y scale markings
    themax = 2.5e9 * 10.0 ** - ((160 - self.y_scale) / 50.0)	# value at top of screen
    themax = int(themax)
    l = []
    for j in (5, 6, 7, 8):
      for i in (1, 2, 5):
        l.append(i * 10 ** j)
    for yvalue in l:
      n = themax / yvalue + 1			# Number of lines
      ypixels = self.height / n
      if n < 20:
        break
    dc.SetPen(self.horizPen)
    for i in range(1, 1000):
      y = self.originY - ypixels * i
      if y < chary:
        break
      # Above axis
      dc.DrawLine(originX, y, x3, y)	# y line
      # Below axis
      y = self.originY + ypixels * i
      dc.DrawLine(originX, y, x3, y)	# y line
    self.yscale = float(ypixels) / yvalue
    self.yvalue = yvalue
  def MakeXTicks(self, dc):
    originY = self.originY
    x3 = self.x3
    # Draw the X axis
    dc.SetPen(wx.Pen(conf.color_graphticks,1))
    dc.DrawLine(self.originX, originY, x3, originY)
    # Find the size of the X scale markings in microseconds
    for i in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000):
      xscale = i			# X scale in microseconds
      if application.sample_rate * xscale * 0.000001 > self.width / 30:
        break
    # Draw the X lines
    dc.SetPen(self.horizPen)
    for i in range(1, 999):
      x = int(self.originX + application.sample_rate * xscale * 0.000001 * i + 0.5)
      if x > x3:
        break
      dc.DrawLine(x, 0, x, self.height)	# x line
    self.xscale = xscale
  def MakeText(self, dc):
    if self.running:
      t = "   RUN"
    else:
      t = "   STOP"
    if self.xscale >= 1000:
      t = "%s    X: %d millisec/div" % (t, self.xscale / 1000)
    else:
      t = "%s    X: %d microsec/div" % (t, self.xscale)
    t = "%s   Y: %.0E/div" % (t, self.yvalue)
    dc.DrawText(t, self.originX, self.height - self.chary)
  def OnGraphData(self, data):
    if not self.running:
      if self.fpout:
        for cpx in data:
          re = int(cpx.real)
          im = int(cpx.imag)
          ab = int(abs(cpx))
          ph = math.atan2(im, re) * 360. / (2.0 * math.pi)
          self.fpout.write("%12d %12d %12d %12.1d\n" % (re, im, ab, ph))
      return		# Preserve data on screen
    line = []
    x = self.originX
    ymax = self.height
    for cpx in data:	# cpx is complex raw samples +/- 0 to 2**31-1
      y = cpx.real
      #y = abs(cpx)
      y = self.originY - int(y * self.yscale + 0.5)
      if y > ymax:
        y = ymax
      elif y < 0:
        y = 0
      line.append((x, y))
      x = x + 1
    self.line = line
    self.Refresh()
  def ChangeYscale(self, y_scale):
    self.y_scale = y_scale
    self.doResize = True
  def ChangeYzero(self, y_zero):
    self.y_zero = y_zero
  def SetTxFreq(self, tx_freq, rx_freq):
    pass

class FilterScreen(GraphScreen):
  """Create a graph of the receive filter response."""
  def __init__(self, parent, data_width, graph_width):
    GraphScreen.__init__(self, parent, data_width, graph_width)
    self.y_scale = conf.filter_y_scale
    self.y_zero = conf.filter_y_zero
    self.VFO = 0
    self.txFreq = 0
    self.data = []
    self.sample_rate = QS.get_filter_rate()
  def NewFilter(self):
    self.sample_rate = QS.get_filter_rate()
    self.data = QS.get_filter()
    #self.data = QS.get_tx_filter()
    self.doResize = True
  def OnGraphData(self, data):
    GraphScreen.OnGraphData(self, self.data)
  def ChangeHwFrequency(self, tune, vfo, source, event):
    GraphScreen.SetTxFreq(self, tune, tune)
    application.freqDisplay.Display(tune)
  def SetTxFreq(self, tx_freq, rx_freq):
    pass

class HelpScreen(wx.html.HtmlWindow):
  """Create the screen for the Help button."""
  def __init__(self, parent, width, height):
    wx.html.HtmlWindow.__init__(self, parent, -1, size=(width, height))
    self.y_scale = 0
    self.y_zero = 0
    if "gtk2" in wx.PlatformInfo:
      self.SetStandardFonts()
    self.SetFonts("", "", [10, 12, 14, 16, 18, 20, 22])
    # read in text from file help.html in the directory of this module
    self.LoadFile('help.html')
  def OnGraphData(self, data):
    pass
  def ChangeYscale(self, y_scale):
    pass
  def ChangeYzero(self, y_zero):
    pass
  def OnIdle(self, event):
    pass
  def SetTxFreq(self, tx_freq, rx_freq):
    pass
  def OnLinkClicked(self, link):
    webbrowser.open(link.GetHref(), new=2)

class QMainFrame(wx.Frame):
  """Create the main top-level window."""
  def __init__(self, width, height):
    fp = open('__init__.py')		# Read in the title
    title = fp.readline().strip()[1:]
    fp.close()
    wx.Frame.__init__(self, None, -1, title, wx.DefaultPosition,
        (width, height), wx.DEFAULT_FRAME_STYLE, 'MainFrame')
    self.SetBackgroundColour(conf.color_bg)
    self.Bind(wx.EVT_CLOSE, self.OnBtnClose)
  def OnBtnClose(self, event):
    application.OnBtnClose(event)
    self.Destroy()

## Note: The new amplitude/phase adjustments have ideas provided by Andrew Nilsson, VK6JBL
class QAdjustPhase(wx.Frame):
  """Create a window with amplitude and phase adjustment controls"""
  f_ampl = "Amplitude adjustment %.6f"
  f_phase = "Phase adjustment degrees %.6f"
  def __init__(self, parent, width, rx_tx):
    self.rx_tx = rx_tx		# Must be "rx" or "tx"
    if rx_tx == 'tx':
      self.is_tx = 1
      t = "Adjust Sound Card Transmit Amplitude and Phase"
    else:
      self.is_tx = 0
      t = "Adjust Sound Card Receive Amplitude and Phase"
    wx.Frame.__init__(self, application.main_frame, -1, t, pos=(50, 100), style=wx.CAPTION)
    panel = wx.Panel(self)
    self.MakeControls(panel, width)
    self.Show()
  def MakeControls(self, panel, width):		# Make controls for phase/amplitude adjustment
    self.old_amplitude, self.old_phase = application.GetAmplPhase(self.is_tx)
    self.new_amplitude, self.new_phase = self.old_amplitude, self.old_phase
    sl_max = width * 4 / 10		# maximum +/- value for slider
    self.ampl_scale = float(conf.rx_max_amplitude_correct) / sl_max
    self.phase_scale = float(conf.rx_max_phase_correct) / sl_max
    font = wx.Font(12, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    chary = self.GetCharHeight()
    y = chary * 3 / 10
    # Print available data points
    if conf.bandAmplPhase.has_key("panadapter"):
      self.band = "panadapter"
    else:
      self.band = application.lastBand
    app_vfo = (application.VFO + 500) / 1000
    ap = application.bandAmplPhase
    if not ap.has_key(self.band):
      ap[self.band] = {}
    if not ap[self.band].has_key(self.rx_tx):
      ap[self.band][self.rx_tx] = []
    lst = ap[self.band][self.rx_tx]
    freq_in_list = False
    if lst:
      t = "Band %s: VFO" % self.band
      for l in lst:
        vfo = (l[0] + 500) / 1000
        if vfo == app_vfo:
          freq_in_list = True
        t = t + (" %d" % vfo)
    else:
      t = "Band %s: No data." % self.band
    txt = wx.StaticText(panel, -1, t, pos=(0, y))
    txt.SetFont(font)
    y += txt.GetSizeTuple()[1]
    self.t_ampl = wx.StaticText(panel, -1, self.f_ampl % self.old_amplitude, pos=(0, y))
    self.t_ampl.SetFont(font)
    y += self.t_ampl.GetSizeTuple()[1]
    self.ampl1 = wx.Slider(panel, -1, 0, -sl_max, sl_max,
      pos=(0, y), size=(width, -1))
    y += self.ampl1.GetSizeTuple()[1]
    self.ampl2 = wx.Slider(panel, -1, 0, -sl_max, sl_max,
      pos=(0, y), size=(width, -1))
    y += self.ampl2.GetSizeTuple()[1]
    self.PosAmpl(self.old_amplitude)
    self.t_phase = wx.StaticText(panel, -1, self.f_phase % self.old_phase, pos=(0, y))
    self.t_phase.SetFont(font)
    y += self.t_phase.GetSizeTuple()[1]
    self.phase1 = wx.Slider(panel, -1, 0, -sl_max, sl_max,
      pos=(0, y), size=(width, -1))
    y += self.phase1.GetSizeTuple()[1]
    self.phase2 = wx.Slider(panel, -1, 0, -sl_max, sl_max,
      pos=(0, y), size=(width, -1))
    y += self.phase2.GetSizeTuple()[1]
    sv = QuiskPushbutton(panel, self.OnBtnSave, 'Save %d' % app_vfo)
    ds = QuiskPushbutton(panel, self.OnBtnDiscard, 'Destroy %d' % app_vfo)
    cn = QuiskPushbutton(panel, self.OnBtnCancel, 'Cancel')
    w, h = ds.GetSizeTuple()
    sv.SetSize((w, h))
    cn.SetSize((w, h))
    y += h / 4
    x = (width - w * 3) / 4
    sv.SetPosition((x, y))
    ds.SetPosition((x*2 + w, y))
    cn.SetPosition((x*3 + w*2, y))
    sv.SetBackgroundColour('light blue')
    ds.SetBackgroundColour('light blue')
    cn.SetBackgroundColour('light blue')
    if not freq_in_list:
      ds.Disable()
    y += h
    y += h / 4
    self.ampl1.SetBackgroundColour('aquamarine')
    self.ampl2.SetBackgroundColour('orange')
    self.phase1.SetBackgroundColour('aquamarine')
    self.phase2.SetBackgroundColour('orange')
    self.PosPhase(self.old_phase)
    self.SetClientSizeWH(width, y)
    self.ampl1.Bind(wx.EVT_SCROLL, self.OnChange)
    self.ampl2.Bind(wx.EVT_SCROLL, self.OnAmpl2)
    self.phase1.Bind(wx.EVT_SCROLL, self.OnChange)
    self.phase2.Bind(wx.EVT_SCROLL, self.OnPhase2)
  def PosAmpl(self, ampl):	# set pos1, pos2 for amplitude
    pos2 = round(ampl / self.ampl_scale)
    remain = ampl - pos2 * self.ampl_scale
    pos1 = round(remain / self.ampl_scale * 50.0)
    self.ampl1.SetValue(pos1)
    self.ampl2.SetValue(pos2)
  def PosPhase(self, phase):	# set pos1, pos2 for phase
    pos2 = round(phase / self.phase_scale)
    remain = phase - pos2 * self.phase_scale
    pos1 = round(remain / self.phase_scale * 50.0)
    self.phase1.SetValue(pos1)
    self.phase2.SetValue(pos2)
  def OnChange(self, event):
    ampl = self.ampl_scale * self.ampl1.GetValue() / 50.0 + self.ampl_scale * self.ampl2.GetValue()
    if abs(ampl) < self.ampl_scale * 3.0 / 50.0:
      ampl = 0.0
    self.t_ampl.SetLabel(self.f_ampl % ampl)
    phase = self.phase_scale * self.phase1.GetValue() / 50.0 + self.phase_scale * self.phase2.GetValue()
    if abs(phase) < self.phase_scale * 3.0 / 50.0:
      phase = 0.0
    self.t_phase.SetLabel(self.f_phase % phase)
    QS.set_ampl_phase(ampl, phase, self.is_tx)
    self.new_amplitude, self.new_phase = ampl, phase
  def OnAmpl2(self, event):		# re-center the fine slider when the coarse slider is adjusted
    ampl = self.ampl_scale * self.ampl1.GetValue() / 50.0 + self.ampl_scale * self.ampl2.GetValue()
    self.PosAmpl(ampl)
    self.OnChange(event)
  def OnPhase2(self, event):	# re-center the fine slider when the coarse slider is adjusted
    phase = self.phase_scale * self.phase1.GetValue() / 50.0 + self.phase_scale * self.phase2.GetValue()
    self.PosPhase(phase)
    self.OnChange(event)
  def DeleteEqual(self):	# Remove entry with the same VFO
    ap = application.bandAmplPhase
    lst = ap[self.band][self.rx_tx]
    vfo = (application.VFO + 500) / 1000
    for i in range(len(lst)-1, -1, -1):
      if (lst[i][0] + 500) / 1000 == vfo:
        del lst[i]
  def OnBtnSave(self, event):
    data = (application.VFO, application.rxFreq, self.new_amplitude, self.new_phase)
    self.DeleteEqual()
    ap = application.bandAmplPhase
    lst = ap[self.band][self.rx_tx]
    lst.append(data)
    lst.sort()
    application.w_phase = None
    self.Destroy()
  def OnBtnDiscard(self, event):
    self.DeleteEqual()
    self.OnBtnCancel()
  def OnBtnCancel(self, event=None):
    QS.set_ampl_phase(self.old_amplitude, self.old_phase, self.is_tx)
    application.w_phase = None
    self.Destroy()

class Spacer(wx.Window):
  """Create a bar between the graph screen and the controls"""
  def __init__(self, parent):
    wx.Window.__init__(self, parent, pos = (0, 0),
       size=(-1, 6), style = wx.NO_BORDER)
    self.Bind(wx.EVT_PAINT, self.OnPaint)
    r, g, b = parent.GetBackgroundColour().Get()
    dark = (r * 7 / 10, g * 7 / 10, b * 7 / 10)
    light = (r + (255 - r) * 5 / 10, g + (255 - g) * 5 / 10, b + (255 - b) * 5 / 10)
    self.dark_pen = wx.Pen(dark, 1, wx.SOLID)
    self.light_pen = wx.Pen(light, 1, wx.SOLID)
    self.width = application.screen_width
  def OnPaint(self, event):
    dc = wx.PaintDC(self)
    w = self.width
    dc.SetPen(self.dark_pen)
    dc.DrawLine(0, 0, w, 0)
    dc.DrawLine(0, 1, w, 1)
    dc.DrawLine(0, 2, w, 2)
    dc.SetPen(self.light_pen)
    dc.DrawLine(0, 3, w, 3)
    dc.DrawLine(0, 4, w, 4)
    dc.DrawLine(0, 5, w, 5)

class App(wx.App):
  """Class representing the application."""
  StateNames = [		# Names of state attributes to save and restore
  'bandState', 'bandAmplPhase', 'lastBand', 'VFO', 'txFreq', 'mode',
  'vardecim_set', 'filterAdjBw1', 'levelAGC', 'volumeAudio', 'levelSpot',
  'levelSquelch']
  def __init__(self):
    global application
    application = self
    self.init_path = None
    if sys.stdout.isatty():
      wx.App.__init__(self, redirect=False)
    else:
      wx.App.__init__(self, redirect=True)
  def QuiskText(self, *args, **kw):			# Make our text control available to widget files
    return QuiskText(*args, **kw)
  def QuiskPushbutton(self, *args, **kw):	# Make our buttons available to widget files
    return QuiskPushbutton(*args, **kw)
  def  QuiskRepeatbutton(self, *args, **kw):
    return QuiskRepeatbutton(*args, **kw)
  def QuiskCheckbutton(self, *args, **kw):
    return QuiskCheckbutton(*args, **kw)
  def QuiskCycleCheckbutton(self, *args, **kw):
    return QuiskCycleCheckbutton(*args, **kw)
  def RadioButtonGroup(self, *args, **kw):
    return RadioButtonGroup(*args, **kw)
  def OnInit(self):
    """Perform most initialization of the app here (called by wxPython on startup)."""
    wx.lib.colourdb.updateColourDB()	# Add additional color names
    import quisk_widgets		# quisk_widgets needs the application object
    quisk_widgets.application = self
    del quisk_widgets
    global conf		# conf is the module for all configuration data
    import quisk_conf_defaults as conf
    setattr(conf, 'config_file_path', ConfigPath)
    if os.path.isfile(ConfigPath):	# See if the user has a config file
      setattr(conf, 'config_file_exists', True)
      d = {}
      d.update(conf.__dict__)		# make items from conf available
      execfile(ConfigPath, d)		# execute the user's config file
      if os.path.isfile(ConfigPath2):	# See if the user has a second config file
        execfile(ConfigPath2, d)	# execute the user's second config file
      for k, v in d.items():		# add user's config items to conf
        if k[0] != '_':				# omit items starting with '_'
          setattr(conf, k, v)
    else:
      setattr(conf, 'config_file_exists', False)
    if conf.invertSpectrum:
      QS.invert_spectrum(1)
    self.bandState = {}
    self.bandState.update(conf.bandState)
    self.bandAmplPhase = conf.bandAmplPhase
    # Open hardware file
    global Hardware
    if hasattr(conf, "Hardware"):	# Hardware defined in config file
      Hardware = conf.Hardware(self, conf)
    else:
      Hardware = conf.quisk_hardware.Hardware(self, conf)
    # Initialization - may be over-written by persistent state
    self.clip_time0 = 0		# timer to display a CLIP message on ADC overflow
    self.smeter_db_count = 0	# average the S-meter
    self.smeter_db_sum = 0
    self.smeter_db = 0
    self.smeter_sunits = -87.0
    self.timer = time.time()		# A seconds clock
    self.heart_time0 = self.timer	# timer to call HeartBeat at intervals
    self.save_time0 = self.timer
    self.smeter_db_time0 = self.timer
    self.smeter_sunits_time0 = self.timer
    self.band_up_down = 0			# Are band Up/Down buttons in use?
    self.lastBand = 'Audio'
    self.filterAdjBw1 = 1000
    self.levelAGC = 200				# AGC level control, 0 to 1000
    self.use_AGC = 1				# AGC is in use
    self.levelSquelch = 500			# FM squelch level, 0 to 1000
    self.use_squelch = 1			# squelch is in use
    self.levelSpot = 500			# Spot level control, 10 to 1000
    self.volumeAudio = 300			# audio volume
    self.VFO = 0
    self.ritFreq = 0
    self.txFreq = 0				# Transmit frequency as +/- sample_rate/2
    self.rxFreq = 0				# Receive  frequency as +/- sample_rate/2
    # Quisk control by Hamlib through rig 2
    self.hamlib_clients = []	# list of TCP connections to handle
    if conf.hamlib_port:
      try:
        self.hamlib_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.hamlib_socket.bind(('localhost', conf.hamlib_port))
        self.hamlib_socket.settimeout(0.0)
        self.hamlib_socket.listen(0)	# listen for TCP connections from multiple clients
      except:
        self.hamlib_socket = None
        # traceback.print_exc()
    else:
      self.hamlib_socket = None
    # Quisk control by fldigi
    self.fldigi_freq = None
    self.fldigi_server = None
    self.oldRxFreq = 0			# Last value of self.rxFreq
    self.screen = None
    self.audio_volume = 0.0		# Set output volume, 0.0 to 1.0
    self.sidetone_volume = 0
    self.sound_error = 0
    self.sound_thread = None
    self.mode = conf.default_mode
    self.bottom_widgets = None
    self.color_list = None
    self.color_index = 0
    self.vardecim_set = None
    self.w_phase = None
    self.zoom = 1.0
    self.filter_bandwidth = 1000
    self.zoom_deltaf = 0
    self.zooming = False
    self.split_rxtx = False	# Are we in split Rx/Tx mode?
    self.savedState = {}
    self.pttButton = None
    self.tmp_playing = False
    # get the screen size - thanks to Lucian Langa
    x, y, self.screen_width, self.screen_height = wx.Display().GetGeometry()
    self.Bind(wx.EVT_IDLE, self.OnIdle)
    self.Bind(wx.EVT_QUERY_END_SESSION, self.OnEndSession)
    # Restore persistent program state
    if conf.persistent_state:
      self.init_path = os.path.join(os.path.dirname(ConfigPath), '.quisk_init.pkl')
      try:
        fp = open(self.init_path, "rb")
        d = pickle.load(fp)
        fp.close()
        for k, v in d.items():
          if k in self.StateNames:
            self.savedState[k] = v
            if k == 'bandState':
              self.bandState.update(v)
            else:
              setattr(self, k, v)
      except:
        pass #traceback.print_exc()
      for k, (vfo, tune, mode) in self.bandState.items():	# Historical: fix bad frequencies
        try:
          f1, f2 = conf.BandEdge[k]
          if not f1 <= vfo + tune <= f2:
            self.bandState[k] = conf.bandState[k]
        except KeyError:
          pass
    if self.bandAmplPhase and type(self.bandAmplPhase.values()[0]) is not DictType:
      print """Old sound card amplitude and phase corrections must be re-entered (sorry).
The new code supports multiple corrections per band."""
      self.bandAmplPhase = {}
    if Hardware.VarDecimGetChoices():	# Hardware can change the decimation.
      self.sample_rate = Hardware.VarDecimSet()	# Get the sample rate.
      self.vardecim_set = self.sample_rate
    else:		# Use the sample rate from the config file.
      self.sample_rate = conf.sample_rate
    if not hasattr(conf, 'playback_rate'):
      if conf.use_sdriq or conf.use_rx_udp:
        conf.playback_rate = 48000
      else:
        conf.playback_rate = conf.sample_rate
    # Find the data width from a list of prefered sizes; it is the width of returned graph data.
    # The graph_width is the width of data_width that is displayed.
    width = self.screen_width * conf.graph_width
    percent = conf.display_fraction		# display central fraction of total width
    percent = int(percent * 100.0 + 0.4)
    width = width * 100 / percent
    for x in fftPreferedSizes:
      if x > width:
        self.data_width = x
        break
    else:
      self.data_width = fftPreferedSizes[-1]
    self.graph_width = self.data_width * percent / 100
    if self.graph_width % 2 == 1:		# Both data_width and graph_width are even numbers
      self.graph_width += 1
    # The FFT size times the average_count controls the graph refresh rate
    factor = float(self.sample_rate) / conf.graph_refresh / self.data_width
    ifactor = int(factor + 0.5)
    if conf.fft_size_multiplier >= ifactor:	# Use large FFT and average count 1
      fft_mult = ifactor
      average_count = 1
    elif conf.fft_size_multiplier > 0:		# Specified fft_size_multiplier
      fft_mult = conf.fft_size_multiplier
      average_count = int(factor / fft_mult + 0.5)
      if average_count < 1:
        average_count = 1
    else:			# Calculate the split between fft size and average
      if self.sample_rate <= 240000:
        maxfft = 8000		# Maximum fft size
      else:
        maxfft = 15000
      fft1 = maxfft / self.data_width
      if fft1 >= ifactor:
        fft_mult = ifactor
        average_count = 1
      else:
        av1 = int(factor / fft1 + 0.5)
        if av1 < 1:
          av1 = 1
        err1 = factor / (fft1 * av1)
        av2 = av1 + 1
        fft2 = int(factor / av2 + 0.5)
        err2 = factor / (fft2 * av2)
        if 0.9 < err1 < 1.1 or abs(1.0 - err1) <= abs(1.0 - err2):
          fft_mult = fft1
          average_count = av1
        else:
          fft_mult = fft2
          average_count = av2
    self.fft_size = self.data_width * fft_mult
    # print 'data, graph,fft', self.data_width, self.graph_width, self.fft_size
    self.width = self.screen_width * 8 / 10
    self.height = self.screen_height * 5 / 10
    self.main_frame = frame = QMainFrame(self.width, self.height)
    self.SetTopWindow(frame)
    # Record the basic application parameters
    if sys.platform == 'win32':
      h = self.main_frame.GetHandle()
    else:
      h = 0
    QS.record_app(self, conf, self.data_width, self.fft_size,
                 average_count, self.sample_rate, h)
    #print 'FFT size %d, FFT mult %d, average_count %d' % (
    #    self.fft_size, self.fft_size / self.data_width, average_count)
    #print 'Refresh %.2f Hz' % (float(self.sample_rate) / self.fft_size / average_count)
    QS.record_graph(0, 0, 1.0)
    # Make all the screens and hide all but one
    self.graph = GraphScreen(frame, self.data_width, self.graph_width)
    self.screen = self.graph
    width = self.graph.width
    button_width = width	# calculate the final button width
    self.config_screen = ConfigScreen(frame, width, self.fft_size)
    self.config_screen.Hide()
    self.waterfall = WaterfallScreen(frame, width, self.data_width, self.graph_width)
    self.waterfall.Hide()
    self.scope = ScopeScreen(frame, width, self.data_width, self.graph_width)
    self.scope.Hide()
    self.filter_screen = FilterScreen(frame, self.data_width, self.graph_width)
    self.filter_screen.Hide()
    self.help_screen = HelpScreen(frame, width, self.screen_height / 10)
    self.help_screen.Hide()
    # Make a vertical box to hold all the screens and the bottom box
    vertBox = self.vertBox = wx.BoxSizer(wx.VERTICAL)
    frame.SetSizer(vertBox)
    # Add the screens
    vertBox.Add(self.config_screen, 1, wx.EXPAND)
    vertBox.Add(self.graph, 1)
    vertBox.Add(self.waterfall, 1)
    vertBox.Add(self.scope, 1)
    vertBox.Add(self.filter_screen, 1)
    vertBox.Add(self.help_screen, 1)
    # Add the spacer
    vertBox.Add(Spacer(frame), 0, wx.EXPAND)
    # Add the bottom box
    hBoxA = wx.BoxSizer(wx.HORIZONTAL)
    vertBox.Add(hBoxA, 0, wx.EXPAND)
    # End of vertical box.  Add items to the horizontal box.
    # Add two sliders on the left
    margin = 3
    self.sliderVol = SliderBoxV(frame, 'Vol', self.volumeAudio, 1000, self.ChangeVolume)
    button_width -= self.sliderVol.width + margin * 2
    self.ChangeVolume()		# set initial volume level
    hBoxA.Add(self.sliderVol, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, margin)
    if Hardware.use_sidetone:
      self.sliderSto = SliderBoxV(frame, 'STo', 300, 1000, self.ChangeSidetone)
      button_width -= self.sliderSto.width + margin * 2
      self.ChangeSidetone()
      hBoxA.Add(self.sliderSto, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, margin)
    # Add the sizer for the middle
    gap = 2
    gbs = wx.GridBagSizer(gap, gap)
    self.gbs = gbs
    button_width -= gap * 15
    hBoxA.Add(gbs, 1, wx.EXPAND, 0)
    gbs.SetEmptyCellSize((5, 5))
    button_width -= 5
    # Add three sliders on the right
    self.sliderYs = SliderBoxV(frame, 'Ys', 0, 160, self.ChangeYscale, True)
    button_width -= self.sliderYs.width + margin * 2
    hBoxA.Add(self.sliderYs, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, margin)
    self.sliderYz = SliderBoxV(frame, 'Yz', 0, 160, self.ChangeYzero, True)
    button_width -= self.sliderYz.width + margin * 2
    hBoxA.Add(self.sliderYz, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, margin)
    self.sliderZo = SliderBoxV(frame, 'Zo', 0, 1000, self.OnChangeZoom)
    button_width -= self.sliderZo.width + margin * 2
    hBoxA.Add(self.sliderZo, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, margin)
    self.sliderZo.SetValue(0)
    button_width /= 12		# This is our final button size
    bw = button_width
    button_width, button_height = self.MakeButtons(frame, gbs, button_width, gap)
    ww = self.graph.width
    self.main_frame.SetSizeHints(ww, 100)
    if button_width > bw:		# The button width was increased
      ww += (button_width - bw) * 12
    self.main_frame.SetClientSizeWH(ww, self.screen_height * 5 / 10)
    self.MakeTopRow(frame, gbs, button_width, button_height)
    self.button_width = button_width
    self.button_height = button_height
    if conf.quisk_widgets:
      self.bottom_widgets = conf.quisk_widgets.BottomWidgets(self, Hardware, conf, frame, gbs, vertBox)
    if QS.open_key(conf.key_method):
      print 'open_key failed for name "%s"' % conf.key_method
    if hasattr(conf, 'mixer_settings'):
      for dev, numid, value in conf.mixer_settings:
        err_msg = QS.mixer_set(dev, numid, value)
        if err_msg:
          print "Mixer", err_msg
    # Open the hardware.  This must be called before open_sound().
    self.config_text = Hardware.open()
    if not self.config_text:
      self.config_text = "Missing config_text"
    if conf.use_rx_udp:
      self.add_version = True		# Add firmware version to config text
    else:
      self.add_version = False
    QS.capt_channels (conf.channel_i, conf.channel_q)
    QS.play_channels (conf.channel_i, conf.channel_q)
    QS.micplay_channels (conf.mic_play_chan_I, conf.mic_play_chan_Q)
    # Note: Subsequent calls to set channels must not name a higher channel number.
    #       Normally, these calls are only used to reverse the channels.
    QS.open_sound(conf.name_of_sound_capt, conf.name_of_sound_play, self.sample_rate,
                conf.data_poll_usec, conf.latency_millisecs,
                conf.microphone_name, conf.tx_ip, conf.tx_audio_port,
                conf.mic_sample_rate, conf.mic_channel_I, conf.mic_channel_Q,
				conf.mic_out_volume, conf.name_of_mic_play, conf.mic_playback_rate)
    tune, vfo = Hardware.ReturnFrequency()	# Request initial frequency
    if tune is None or vfo is None:		# Set last-used frequency
      self.bandBtnGroup.SetLabel(self.lastBand, do_cmd=True)
    else:			# Set requested frequency
      self.BandFromFreq(tune)
      self.ChangeDisplayFrequency(tune - vfo, vfo)
    # Record filter rate for the filter screen
    self.filter_screen.sample_rate = QS.get_filter_rate()
    #if info[8]:		# error message
    #  self.sound_error = 1
    #  self.config_screen.err_msg = info[8]
    #  print info[8]
    self.config_screen.InitBitmap()
    if self.sound_error:
      self.screenBtnGroup.SetLabel('Config', do_cmd=True)
      frame.Show()
    else:
      self.screenBtnGroup.SetLabel(conf.default_screen, do_cmd=True)
      frame.Show()
      self.Yield()
      self.sound_thread = SoundThread()
      self.sound_thread.start()
    return True
  def OnIdle(self, event):
    if self.screen:
      self.screen.OnIdle(event)
  def OnEndSession(self, event):
    event.Skip()
    self.OnBtnClose(event)
  def OnBtnClose(self, event):
    QS.set_file_record(3, '')	# Turn off file recording
    time.sleep(0.1)
    if self.sound_thread:
      self.sound_thread.stop()
    for i in range(0, 20):
      if threading.activeCount() == 1:
        break
      time.sleep(0.1)
  def OnExit(self):
    QS.close_rx_udp()
    Hardware.close()
    self.SaveState()
  def CheckState(self):		# check whether state has changed
    changed = False
    if self.init_path:		# save current program state
      for n in self.StateNames:
        try:
          if getattr(self, n) != self.savedState[n]:
            changed = True
            break
        except:
          changed = True
          break
    return changed
  def SaveState(self):
    if self.init_path:		# save current program state
      d = {}
      for n in self.StateNames:
        d[n] = v = getattr(self, n)
        self.savedState[n] = v
      try:
        fp = open(self.init_path, "wb")
        pickle.dump(d, fp)
        fp.close()
      except:
        pass #traceback.print_exc()
  def MakeTopRow(self, frame, gbs, button_width, button_height):
    # Down button
    b_down = QuiskRepeatbutton(frame, self.OnBtnDownBand, "Down",
             self.OnBtnUpDnBandDone, use_right=True)
    gbs.Add(b_down, (0, 4), flag=wx.ALIGN_CENTER)
    # Up button
    b_up = QuiskRepeatbutton(frame, self.OnBtnUpBand, "Up",
             self.OnBtnUpDnBandDone, use_right=True)
    gbs.Add(b_up, (0, 5), flag=wx.ALIGN_CENTER)
    # RIT button
    self.ritButton = QuiskCheckbutton(frame, self.OnBtnRit, "RIT")
    gbs.Add(self.ritButton, (0, 7), flag=wx.ALIGN_CENTER)
    bw, bh = b_down.GetMinSize()		# make these buttons the same size
    bw = (bw + button_width) / 2
    b_down.SetSizeHints        (bw, button_height, bw * 5, button_height)
    b_up.SetSizeHints          (bw, button_height, bw * 5, button_height)
    self.ritButton.SetSizeHints(bw, button_height, bw * 5, button_height)
    # RIT slider
    self.ritScale = wx.Slider(frame, -1, self.ritFreq, -2000, 2000, size=(-1, -1), style=wx.SL_LABELS)
    self.ritScale.Bind(wx.EVT_SCROLL, self.OnRitScale)
    gbs.Add(self.ritScale, (0, 8), (1, 3), flag=wx.EXPAND)
    sw, sh = self.ritScale.GetSize()
    # Frequency display
    h = max(button_height, sh)		# larger of button and slider height
    self.freqDisplay = FrequencyDisplay(frame, gbs, button_width * 25 / 10, h)
    self.freqDisplay.Display(self.txFreq + self.VFO)
    # Frequency entry
    e = wx.TextCtrl(frame, -1, '', style=wx.TE_PROCESS_ENTER)
    font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.NORMAL, wx.FONTWEIGHT_NORMAL)
    e.SetFont(font)
    w, h = e.GetSizeTuple()
    border = (self.freqDisplay.height_and_border - h) / 2
    e.SetMinSize((1, 1))
    e.SetBackgroundColour(conf.color_entry)
    gbs.Add(e, (0, 3), flag = wx.EXPAND | wx.TOP | wx.BOTTOM, border=border)
    frame.Bind(wx.EVT_TEXT_ENTER, self.FreqEntry, source=e)
    # S-meter
    self.smeter = QuiskText(frame, ' S9+23 -166.00 dB ', bh, wx.ALIGN_LEFT, True)
    gbs.Add(self.smeter, (0, 11), (1, 2), flag=wx.EXPAND)
  def MakeButtons(self, frame, gbs, button_width, gap):
    # There are six columns, a small gap column, and then six more columns
    ### Left bank of buttons
    flag = wx.EXPAND
    # Band buttons are put into a box sizer that spans the first six buttons
    self.bandBtnGroup = RadioButtonGroup(frame, self.OnBtnBand, conf.bandLabels, None)
    band_buttons = self.bandBtnGroup.buttons
    szr = wx.BoxSizer(wx.HORIZONTAL)
    gbs.Add(szr, (1, 0), (1, 6))
    band_length = 0
    for b in band_buttons:	# Get the total length
      szr.Add(b, 0)
      w, h = b.GetMinSize()
      band_length += w
    band_size = (band_length - gap * 5) / 6 + 1			# Button size needed by band buttons
    # Receive button row: Mute, AGC
    left_buttons = []
    b = QuiskCheckbutton(frame, self.OnBtnMute, text='Mute')
    left_buttons.append(b)
    self.BtnAGC = QuiskSliderButton(frame, self.OnBtnAGC, 'AGC')   # AGC and Squelch
    left_buttons.append(self.BtnAGC)
    b = QuiskCycleCheckbutton(frame, self.OnBtnNB, ('NB', 'NB 1', 'NB 2', 'NB 3'))
    left_buttons.append(b)
    try:
      labels = Hardware.rf_gain_labels
    except:
      labels = ()
    if labels:
      b = self.BtnRfGain = QuiskCycleCheckbutton(frame, Hardware.OnButtonRfGain, labels)
    else:
      b = QuiskCheckbutton(frame, None, text='RfGain')
      b.Enable(False)
      self.BtnRfGain = None
    left_buttons.append(b)
    try:
      labels = Hardware.antenna_labels
    except:
      labels = ()
    if labels:
      b = QuiskCycleCheckbutton(frame, Hardware.OnButtonAntenna, labels)
    else:
      b = QuiskCheckbutton(frame, None, text='Ant 1')
      b.Enable(False)
    left_buttons.append(b)
    if 0:	# Display a color chooser
      b = QuiskRepeatbutton(frame, self.OnBtnColor, 'Color', use_right=True)
    else:
      b = QuiskCheckbutton(frame, self.OnBtnTest1, 'Test 1', color=conf.color_test)
    left_buttons.append(b)
    for col in range(0, 6):
      gbs.Add(left_buttons[col], (2, col), flag=flag)
    # Transmit button row: Spot
    b = QuiskSpotButton(frame, self.OnBtnSpot, 'Spot', slider_value=self.levelSpot,
         color=conf.color_test, slider_min=10, slider_max=1000)
    if not hasattr(Hardware, 'OnSpot'):
      b.Enable(False)
    left_buttons.append(b)
    b = self.splitButton = QuiskCheckbutton(frame, self.OnBtnSplit, "Split")
    if conf.mouse_tune_method:		# Mouse motion changes the VFO frequency
      b.Enable(False)
    left_buttons.append(b)
    b = QuiskCheckbutton(frame, self.OnBtnFDX, 'FDX', color=conf.color_test)
    if not conf.add_fdx_button:
      b.Enable(False)
    left_buttons.append(b)
    if hasattr(Hardware, 'OnButtonPTT'):
      b = QuiskCheckbutton(frame, Hardware.OnButtonPTT, 'PTT', color='red')
      self.pttButton = b
    else:
      b = QuiskCheckbutton(frame, None, 'PTT')
      b.Enable(False)
    left_buttons.append(b)
    # Record and Playback buttons in a box sizer
    sizer = wx.BoxSizer()
    b = self.btnTmpRecord = QuiskCheckbutton(frame, self.OnBtnTmpRecord, text='Rec')
    sizer.Add(b, 1, wx.EXPAND)
    b = self.btnTmpPlay = QuiskCheckbutton(frame, self.OnBtnTmpPlay, text='Play')
    b.Enable(0)
    sizer.Add(b, 1, wx.EXPAND)
    left_buttons.append(sizer)
    self.btn_file_record = QuiskCheckbutton(frame, self.OnBtnFileRecord, 'File Rec')
    self.btn_file_record.Enable(0)
    left_buttons.append(self.btn_file_record)
    for col in range(0, 6):
      gbs.Add(left_buttons[col + 6], (3, col), flag=flag)
    ### Right bank of buttons
    labels = [('CWL', 'CWU'), ('LSB', 'USB'), 'AM', 'FM', 'DGTL']
    if conf.add_imd_button:
      labels.append(('IMD', 'IMD -3dB', 'IMD -6dB'))
    elif conf.add_extern_demod:
      labels.append(conf.add_extern_demod)
    else:
      labels.append('')
    self.modeButns = RadioButtonGroup(frame, self.OnBtnMode, labels, None)
    right_buttons = self.modeButns.GetButtons()[:]
    if conf.add_imd_button:
      right_buttons[-1].color = conf.color_test
    labels = ('0', '0', '0', '0', '0', '0')
    self.filterButns = RadioButtonGroup(frame, self.OnBtnFilter, labels, None)
    b = QuiskFilterButton(frame, text=str(self.filterAdjBw1))
    self.filterButns.ReplaceButton(5, b)
    right_buttons += self.filterButns.GetButtons()
    labels = (('Graph', 'GraphP1', 'GraphP2'), 'WFall', ('Scope', 'Scope'), 'Config', 'RX Filter', 'Help')
    self.screenBtnGroup = RadioButtonGroup(frame, self.OnBtnScreen, labels, conf.default_screen)
    right_buttons += self.screenBtnGroup.GetButtons()
    col = 7
    for i in range(0, 6):
      gbs.Add(right_buttons[i], (1, col), flag=flag)
      gbs.Add(right_buttons[i+6], (2, col), flag=flag)
      gbs.Add(right_buttons[i+12], (3, col), flag=flag)
      col += 1
    bsize = 0		# Find size of largest button
    for b in left_buttons + right_buttons:
      w, height = b.GetMinSize()
      if bsize < w:
        bsize = w
    # Perhaps increase the requested button width
    button_width = max(bsize, band_size, button_width)
    # Adjust size of buttons
    for b in left_buttons + right_buttons:
      b.SetMinSize((button_width, height))
    # Adjust size of band buttons
    width = button_width * 6 + gap * 5		# Final size of band button row
    add = width - band_length
    add = add / len(band_buttons)			# Amount to add to each band button to fill space
    for b in band_buttons[0:-1]:
      w, h = b.GetMinSize()
      w += add
      b.SetMinSize((w, h))
      width -= w
    band_buttons[-1].SetMinSize((width, h))
    # return the button size
    return button_width, height
  def NewSmeter(self):
    #avg_seconds = 5.0				# seconds for S-meter average
    avg_seconds = 1.0
    self.smeter_db_count += 1		# count for average
    x = QS.get_smeter()
    self.smeter_db_sum += x		# sum for average
    if self.timer - self.smeter_db_time0 > avg_seconds:		# average time reached
      self.smeter_db = self.smeter_db_sum / self.smeter_db_count
      self.smeter_db_count = self.smeter_db_sum = 0 
      self.smeter_db_time0 = self.timer
    if self.smeter_sunits < x:		# S-meter moves to peak value
      self.smeter_sunits = x
    else:			# S-meter decays at this time constant
      self.smeter_sunits -= (self.smeter_sunits - x) * (self.timer - self.smeter_sunits_time0)
    self.smeter_sunits_time0 = self.timer
    s = self.smeter_sunits / 6.0	# change to S units; 6db per S unit
    s += Hardware.correct_smeter	# S-meter correction for the gain, band, etc.
    if s < 0:
      s = 0
    if s >= 9.5:
      s = (s - 9.0) * 6
      t = "  S9+%2.0f %7.2f dB" % (s, self.smeter_db)
    else:
      t = "  S%.0f    %7.2f dB" % (s, self.smeter_db)
    self.smeter.SetLabel(t)
  def MakeFilterButtons(self, args):
    # Change the filter selections depending on the mode: CW, SSB, etc.
    # Do not change the adjustable filter buttons.
    buttons = self.filterButns.GetButtons()
    for i in range(0, len(buttons) - 1):
      buttons[i].SetLabel(str(args[i]))
      buttons[i].Refresh()
  def MakeFilterCoef(self, rate, N, bw, center):
    """Make an I/Q filter with rectangular passband."""
    lowpass = bw * 24000 / rate / 2
    if Filters.has_key(lowpass):
      filtD = Filters[lowpass]
    else:
      if N is None:
        shape = 1.5       # Shape factor at 88 dB
        trans = (bw / 2.0 / rate) * (shape - 1.0)     # 88 dB atten
        N = int(4.0 / trans)
        if N > 1000:
          N = 1000
        N = (N / 2) * 2 + 1
      K = bw * N / rate
      filtD = []
      pi = math.pi
      sin = math.sin
      cos = math.cos
      for k in range(-N/2, N/2 + 1):
        # Make a lowpass filter
        if k == 0:
          z = float(K) / N
        else:
          z = 1.0 / N * sin(pi * k * K / N) / sin(pi * k / N)
        # Apply a windowing function
        if 1:	# Blackman window
          w = 0.42 + 0.5 * cos(2. * pi * k / N) + 0.08 * cos(4. * pi * k / N)
        elif 0:	# Hamming
          w = 0.54 + 0.46 * cos(2. * pi * k / N)
        elif 0:	# Hanning
          w = 0.5 + 0.5 * cos(2. * pi * k / N)
        else:
          w = 1
        z *= w
        filtD.append(z)
    if center:
      # Make a bandpass filter by tuning the low pass filter to new center frequency.
      # Make two quadrature filters.
      filtI = []
      filtQ = []
      tune = -1j * 2.0 * math.pi * center / rate;
      NN = len(filtD)
      D = (NN - 1.0) / 2.0;
      for i in range(NN):
        z = 2.0 * cmath.exp(tune * (i - D)) * filtD[i]
        filtI.append(z.real)
        filtQ.append(z.imag)
      return filtI, filtQ
    return filtD, filtD
  def UpdateFilterDisplay(self):
    # Note: Filter bandwidths are ripple bandwidths with a shape factor of 1.2.
    # Also, SSB filters start at 300 Hz.
    if not conf.filter_display:
      size = 1
      tune = 0
    elif self.mode in ('AM', 'FM', 'CWL', 'CWU'):
      size = int(self.filter_bandwidth / self.zoom / self.sample_rate * self.data_width + 0.5)
      tune = size / 2
    elif self.mode == 'LSB':
      size = int((self.filter_bandwidth + 300) / self.zoom / self.sample_rate * self.data_width + 0.5)
      tune = size - 1
    else:
      size = int((self.filter_bandwidth + 300) / self.zoom / self.sample_rate * self.data_width + 0.5)
      tune = 0
    if size < 2:
      size = 1
      tune = 0
    self.graph.display.UpdateFilterDisplay(size, tune)
    self.waterfall.pane1.display.UpdateFilterDisplay(size, tune)
  def OnBtnFilter(self, event, bw=None):
    if event is None:	# called by application
      self.filterButns.SetLabel(str(bw))
    else:		# called by button
      btn = event.GetEventObject()
      bw = int(btn.GetLabel())
    mode = self.mode
    if mode in ("CWL", "CWU"):
      bw = min(bw, 2500)
      center = max(conf.cwTone, bw/2)
    elif mode in ('LSB', 'USB', 'DGTL'):
      bw = min(bw, 5000)
      center = 300 + bw / 2
    elif mode == 'AM':
      bw = min(bw, 21000)
      center = 0
    elif mode == 'FM':
      bw = min(bw, 21000)
      center = 0
    else:
      bw = min(bw, 5000)
      center = 300 + bw / 2
    self.filter_bandwidth = bw
    self.UpdateFilterDisplay()
    frate = QS.get_filter_rate()
    filtI, filtQ = self.MakeFilterCoef(frate, None, bw, center)
    QS.set_filters(filtI, filtQ, bw)
    if self.screen is self.filter_screen:
      self.screen.NewFilter()
  def OnBtnScreen(self, event, name=None):
    if event is not None:
      win = event.GetEventObject()
      name = win.GetLabel()
    self.screen.Hide()
    if name == 'Config':
      self.screen = self.config_screen
    elif name[0:5] == 'Graph':
      self.screen = self.graph
      self.screen.SetTxFreq(self.txFreq, self.rxFreq)
      self.freqDisplay.Display(self.VFO + self.txFreq)
      self.screen.PeakHold(name)
    elif name == 'WFall':
      self.screen = self.waterfall
      self.screen.SetTxFreq(self.txFreq, self.rxFreq)
      self.freqDisplay.Display(self.VFO + self.txFreq)
      sash = self.screen.GetSashPosition()
    elif name == 'Scope':
      if win.direction:				# Another push on the same button
        self.scope.running = 1 - self.scope.running		# Toggle run state
      else:				# Initial push of button
        self.scope.running = 1
      self.screen = self.scope
    elif name == 'RX Filter':
      self.screen = self.filter_screen
      self.freqDisplay.Display(self.screen.txFreq)
      self.screen.NewFilter()
    elif name == 'Help':
      self.screen = self.help_screen
    self.screen.Show()
    self.vertBox.Layout()	# This destroys the initialized sash position!
    self.sliderYs.SetValue(self.screen.y_scale)
    self.sliderYz.SetValue(self.screen.y_zero)
    if name == 'WFall':
      self.screen.SetSashPosition(sash)
  def OnBtnFileRecord(self, event):
    if event.GetEventObject().GetValue():
      QS.set_file_record(2, '')
    else:
      QS.set_file_record(3, '')
  def ChangeYscale(self, event):
    self.screen.ChangeYscale(self.sliderYs.GetValue())
  def ChangeYzero(self, event):
    self.screen.ChangeYzero(self.sliderYz.GetValue())
  def OnChangeZoom(self, event):
    x = self.sliderZo.GetValue()
    if x < 50:
      self.zoom = 1.0	# change back to not-zoomed mode
      self.zoom_deltaf = 0
      self.zooming = False
    else:
      a = 1000.0 * self.sample_rate / (self.sample_rate - 2500.0)
      self.zoom = 1.0 - x / a
      if not self.zooming:
        self.zoom_deltaf = self.txFreq		# set deltaf when zoom mode starts
        self.zooming = True
    zoom = self.zoom
    deltaf = self.zoom_deltaf
    self.graph.ChangeZoom(zoom, deltaf)
    self.waterfall.pane1.ChangeZoom(zoom, deltaf)
    self.waterfall.pane2.ChangeZoom(zoom, deltaf)
    self.waterfall.pane2.display.ChangeZoom(zoom, deltaf)
    self.screen.SetTxFreq(self.txFreq, self.rxFreq)
    self.UpdateFilterDisplay()
  def OnBtnMute(self, event):
    btn = event.GetEventObject()
    if btn.GetValue():
      QS.set_volume(0)
    else:
      QS.set_volume(self.audio_volume)
  def OnBtnDecimation(self, event):
    i = event.GetSelection()
    rate = Hardware.VarDecimSet(i)
    self.vardecim_set = rate
    if rate != self.sample_rate:
      self.sample_rate = rate
      self.graph.sample_rate = rate
      self.waterfall.pane1.sample_rate = rate
      self.waterfall.pane2.sample_rate = rate
      self.waterfall.pane2.display.sample_rate = rate
      average_count = float(rate) / conf.graph_refresh / self.fft_size
      average_count = int(average_count + 0.5)
      average_count = max (1, average_count)
      QS.change_rate(rate, average_count)
      tune = self.txFreq
      vfo = self.VFO
      self.txFreq = self.VFO = -1		# demand change
      self.ChangeHwFrequency(tune, vfo, 'NewDecim')
      self.UpdateFilterDisplay()
  def ChangeVolume(self, event=None):
    # Caution: event can be None
    value = self.sliderVol.GetValue()
    self.volumeAudio = 1000 - value
    # Simulate log taper pot
    x = (10.0 ** (float(value) * 0.003000434077) - 1) / 1000.0
    self.audio_volume = x	# audio_volume is 0 to 1.000
    QS.set_volume(x)
  def ChangeSidetone(self, event=None):
    # Caution: event can be None
    value = self.sliderSto.GetValue()
    self.sidetone_volume = value
    QS.set_sidetone(value, self.ritFreq, conf.keyupDelay)
  def OnRitScale(self, event=None):	# Called when the RIT slider is moved
    # Caution: event can be None
    if self.ritButton.GetValue():
      value = self.ritScale.GetValue()
      value = int(value)
      self.ritFreq = value
      QS.set_tune(self.rxFreq + self.ritFreq, self.txFreq)
      QS.set_sidetone(self.sidetone_volume, self.ritFreq, conf.keyupDelay)
  def OnBtnSplit(self, event):	# Called when the Split check button is pressed
    self.split_rxtx = self.splitButton.GetValue()
    if self.split_rxtx:
      self.rxFreq = self.oldRxFreq
      d = self.sample_rate * 49 / 100	# Move rxFreq on-screen
      if self.rxFreq < -d:
        self.rxFreq = -d
      elif self.rxFreq > d:
        self.rxFreq = d
    else:
      self.oldRxFreq = self.rxFreq
      self.rxFreq = self.txFreq
    self.screen.SetTxFreq(self.txFreq, self.rxFreq)
    QS.set_tune(self.rxFreq + self.ritFreq, self.txFreq)
  def OnBtnRit(self, event=None):	# Called when the RIT check button is pressed
    # Caution: event can be None
    if self.ritButton.GetValue():
      self.ritFreq = self.ritScale.GetValue()
    else:
      self.ritFreq = 0
    QS.set_tune(self.rxFreq + self.ritFreq, self.txFreq)
    QS.set_sidetone(self.sidetone_volume, self.ritFreq, conf.keyupDelay)
  def SetRit(self, freq):
    if freq:
      self.ritButton.SetValue(1)
    else:
      self.ritButton.SetValue(0)
    self.ritScale.SetValue(freq)
    self.OnBtnRit()
  def OnBtnFDX(self, event):
    btn = event.GetEventObject()
    if btn.GetValue():
      QS.set_fdx(1)
    else:
      QS.set_fdx(0)
  def OnBtnSpot(self, event):
    btn = event.GetEventObject()
    self.levelSpot = btn.slider_value
    if btn.GetValue():
      value = btn.slider_min + btn.slider_max - btn.slider_value	# slider values are backwards in Wx
    else:
      value = 0
    QS.set_spot_level(value)
    Hardware.OnSpot(value)
  def OnBtnTmpRecord(self, event):
    btn = event.GetEventObject()
    if btn.GetValue():
      self.btnTmpPlay.Enable(0)
      QS.set_record_state(0)
    else:
      self.btnTmpPlay.Enable(1)
      QS.set_record_state(1)
  def OnBtnTmpPlay(self, event):
    btn = event.GetEventObject()
    if btn.GetValue():
      if QS.is_key_down() and conf.mic_sample_rate != conf.playback_rate:
        self.btnTmpPlay.SetValue(False, False)
      else:
        self.btnTmpRecord.Enable(0)
        QS.set_record_state(2)
        self.tmp_playing = True
    else:
      self.btnTmpRecord.Enable(1)
      QS.set_record_state(3)
      self.tmp_playing = False
  def OnBtnTest1(self, event):
    btn = event.GetEventObject()
    if btn.GetValue():
      QS.add_tone(10000)
    else:
      QS.add_tone(0)
  def OnBtnTest2(self, event):
    return
  def OnBtnColor(self, event):
    if not self.color_list:
      clist = wx.lib.colourdb.getColourInfoList()
      self.color_list = [(0, clist[0][0])]
      self.color_index = 0
      for i in range(1, len(clist)):
        if  self.color_list[-1][1].replace(' ', '') != clist[i][0].replace(' ', ''):
          #if 'BLUE' in clist[i][0]:
            self.color_list.append((i, clist[i][0]))
    btn = event.GetEventObject()
    if btn.shift:
      del self.color_list[self.color_index]
    else:
      self.color_index += btn.direction
    if self.color_index >= len(self.color_list):
      self.color_index = 0
    elif self.color_index < 0:
      self.color_index = len(self.color_list) -1
    color = self.color_list[self.color_index][1]
    print self.color_index, color
    self.main_frame.SetBackgroundColour(color)
    self.main_frame.Refresh()
    self.screen.Refresh()
    btn.SetBackgroundColour(color)
    btn.Refresh()
  def OnBtnAGC(self, event):    # This is a combined AGC and Squelch button
    btn = event.GetEventObject()
    if self.mode == 'FM':   # This is a Squelch button
      self.levelSquelch = btn.slider_value
      if btn.GetValue():
        self.use_squelch = 1
        value = 1000 - btn.slider_value		# slider values are backwards in Wx
        QS.set_squelch(value / 12.0 - 120.0)
      else:
        self.use_squelch = 0
        QS.set_squelch(-999.0)
    else:                   # This is an AGC button
      self.levelAGC = btn.slider_value
      value = 1000 - btn.slider_value		# slider values are backwards in Wx
      # Simulate log taper pot.  Volume is 0 to 1.000.
      x = (10.0 ** (float(value) * 0.003000434077) - 1) / 1000.0
      if btn.GetValue():
        self.use_AGC = 1
        QS.set_agc(1, x, 0.3)
      else:
        self.use_AGC = 0
        QS.set_agc(0, x, 0.3)
  def OnBtnNB(self, event):
    index = event.GetEventObject().index
    QS.set_noise_blanker(index)
  def FreqEntry(self, event):
    freq = event.GetString()
    if not freq:
      return
    try:
      if '.' in freq:
        freq = int(float(freq) * 1E6 + 0.1)
      else:
        freq = int(freq)
    except ValueError:
      win = event.GetEventObject()
      win.Clear()
      win.AppendText("Error")
    else:
      tune = freq % 10000
      vfo = freq - tune
      self.BandFromFreq(freq)
      self.ChangeHwFrequency(tune, vfo, 'FreqEntry')
  def ChangeHwFrequency(self, tune, vfo, source='', band='', event=None):
    """Change the VFO and tuning frequencies, and notify the hardware.

    tune:   the new tuning frequency in +- sample_rate/2;
    vfo:    the new vfo frequency in Hertz; this is the RF frequency at zero Hz audio
    source: a string indicating the source or widget requesting the change;
    band:   if source is "BtnBand", the band requested;
    event:  for a widget, the event (used to access control/shift key state).

    Try to update the hardware by calling Hardware.ChangeFrequency().
    The hardware will reply with the updated frequencies which may be different
    from those requested; use and display the returned tune and vfo.
    """
    tune, vfo = Hardware.ChangeFrequency(vfo + tune, vfo, source, band, event)
    self.ChangeDisplayFrequency(tune - vfo, vfo)
  def ChangeDisplayFrequency(self, tune, vfo):
    'Change the frequency displayed by Quisk'
    change = 0
    if tune != self.txFreq:
      change = 1
      self.txFreq = tune
      if not self.split_rxtx:
        self.rxFreq = self.txFreq
      self.screen.SetTxFreq(self.txFreq, self.rxFreq)
      QS.set_tune(self.rxFreq + self.ritFreq, self.txFreq)
    if vfo != self.VFO:
      change = 1
      self.VFO = vfo
      self.graph.SetVFO(vfo)
      self.waterfall.SetVFO(vfo)
      if self.w_phase:		# Phase adjustment screen can not change its VFO
        self.w_phase.Destroy()
        self.w_phase = None
      ampl, phase = self.GetAmplPhase(0)
      QS.set_ampl_phase(ampl, phase, 0)
      ampl, phase = self.GetAmplPhase(1)
      QS.set_ampl_phase(ampl, phase, 1)
    if change:
      self.freqDisplay.Display(self.txFreq + self.VFO)
      self.fldigi_freq = self.txFreq + self.VFO
    return change
  def ChangeRxTxFrequency(self, rx_freq=None, tx_freq=None):
    if not self.split_rxtx and not tx_freq:
      tx_freq = rx_freq
    if tx_freq:
      tune = tx_freq - self.VFO
      d = self.sample_rate * 45 / 100
      if -d <= tune <= d:	# Frequency is on-screen
        vfo = self.VFO
      else:					# Change the VFO
        vfo = (tx_freq / 5000) * 5000 - 5000
        tune = tx_freq - vfo
        self.BandFromFreq(tx_freq)
      self.ChangeHwFrequency(tune, vfo, 'FreqEntry')
    if rx_freq and self.split_rxtx:		# Frequency must be on-screen
      tune = rx_freq - self.VFO
      self.rxFreq = tune
      self.screen.SetTxFreq(self.txFreq, tune)
      QS.set_tune(tune + self.ritFreq, self.txFreq)
  def OnBtnMode(self, event, mode=None):
    if event is None:	# called by application
      self.modeButns.SetLabel(mode)
    else:		# called by button
      mode = self.modeButns.GetLabel()
    Hardware.ChangeMode(mode)
    self.mode = mode
    if mode == 'CWL':
      QS.set_rx_mode(0)
      self.SetRit(conf.cwTone)
      self.MakeFilterButtons(conf.FilterBwCW)
      self.OnBtnFilter(None, conf.FilterBwCW[3])
    elif mode == 'CWU':
      QS.set_rx_mode(1)
      self.SetRit(-conf.cwTone)
      self.MakeFilterButtons(conf.FilterBwCW)
      self.OnBtnFilter(None, conf.FilterBwCW[3])
    elif mode == 'LSB':
      QS.set_rx_mode(2)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwSSB)
      self.OnBtnFilter(None, conf.FilterBwSSB[3])
    elif mode == 'USB':
      QS.set_rx_mode(3)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwSSB)
      self.OnBtnFilter(None, conf.FilterBwSSB[3])
    elif mode == 'AM':
      QS.set_rx_mode(4)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwAM)
      self.OnBtnFilter(None, conf.FilterBwAM[3])
    elif mode == 'FM':
      QS.set_rx_mode(5)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwFM)
      self.OnBtnFilter(None, conf.FilterBwFM[3])
    elif mode == 'DGTL':
      QS.set_rx_mode(7)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwSSB)
      self.OnBtnFilter(None, conf.FilterBwSSB[3])
    elif mode[0:3] == 'IMD':
      QS.set_rx_mode(10 + self.modeButns.GetSelectedButton().index)	# 10, 11, 12
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwIMD)
      self.OnBtnFilter(None, conf.FilterBwIMD[3])
    elif mode == conf.add_extern_demod:	# External demodulation
      QS.set_rx_mode(6)
      self.SetRit(0)
      self.MakeFilterButtons(conf.FilterBwEXT)
      self.OnBtnFilter(None, conf.FilterBwEXT[3])
    if mode == 'FM':
      self.BtnAGC.SetLabel('Sqlch')
      self.BtnAGC.SetSlider(self.levelSquelch)
      self.BtnAGC.SetValue(self.use_squelch, True)
    else:
      self.BtnAGC.SetLabel('AGC')
      self.BtnAGC.SetSlider(self.levelAGC)
      self.BtnAGC.SetValue(self.use_AGC, True)
  def OnBtnBand(self, event):
    band = self.lastBand	# former band in use
    try:
      f1, f2 = conf.BandEdge[band]
      if f1 <= self.VFO + self.txFreq <= f2:
        self.bandState[band] = (self.VFO, self.txFreq, self.mode)
    except KeyError:
      pass
    btn = event.GetEventObject()
    band = btn.GetLabel()	# new band
    self.lastBand = band
    try:
      vfo, tune, mode = self.bandState[band]
    except KeyError:
      vfo, tune, mode = (0, 0, 'LSB')
    if band == '60':
      if self.mode in ('CWL', 'CWU'):
        freq60 = []
        for f in conf.freq60:
          freq60.append(f + 1500)
      else:
        freq60 = conf.freq60
      freq = vfo + tune
      if btn.direction:
        vfo = self.VFO
        if 5100000 < vfo < 5600000:
          if btn.direction > 0:		# Move up
            for f in freq60:
              if f > vfo + self.txFreq:
                freq = f
                break
            else:
              freq = freq60[0]
          else:			# move down
            l = list(freq60)
            l.reverse()
            for f in l: 
              if f < vfo + self.txFreq:
                freq = f
                break
              else:
                freq = freq60[-1]
      half = self.sample_rate / 2 * self.graph_width / self.data_width
      while freq - vfo <= -half + 1000:
        vfo -= 10000
      while freq - vfo >= +half - 5000:
        vfo += 10000
      tune = freq - vfo
    elif band == 'Time':
      vfo, tune, mode = conf.bandTime[btn.index]
    self.OnBtnMode(None, mode)
    self.txFreq = self.VFO = -1		# demand change
    self.ChangeHwFrequency(tune, vfo, 'BtnBand', band=band)
    Hardware.ChangeBand(band)
  def BandFromFreq(self, frequency):	# Change to a new band based on the frequency
    try:
      f1, f2 = conf.BandEdge[self.lastBand]
      if f1 <= frequency <= f2:
        return						# We are within the current band
    except KeyError:
      f1 = f2 = -1
    # Frequency is not within the current band.  Save the current band data.
    if f1 <= self.VFO + self.txFreq <= f2:
      self.bandState[self.lastBand] = (self.VFO, self.txFreq, self.mode)
    # Change to the correct band based on frequency.
    for band, (f1, f2) in conf.BandEdge.items():
      if f1 <= frequency <= f2:
        self.lastBand = band
        self.bandBtnGroup.SetLabel(band, do_cmd=False)
        try:
          vfo, tune, mode = self.bandState[band]
        except KeyError:
          vfo, tune, mode = (0, 0, 'LSB')
        self.OnBtnMode(None, mode)
        Hardware.ChangeBand(band)
        break
  def OnBtnUpDnBandDelta(self, event, is_band_down):
    sample_rate = int(self.sample_rate * self.zoom)
    oldvfo = self.VFO
    btn = event.GetEventObject()
    if btn.direction > 0:		# left button was used, move a bit
      d = int(sample_rate / 9)
    else:						# right button was used, move to edge
      d = int(sample_rate * 45 / 100)
    if is_band_down:
      d = -d
    vfo = self.VFO + d
    if sample_rate > 40000:
      vfo = (vfo + 5000) / 10000 * 10000	# round to even number
      delta = 10000
    elif sample_rate > 5000:
      vfo = (vfo + 500) / 1000 * 1000
      delta = 1000
    else:
      vfo = (vfo + 50) / 100 * 100
      delta = 100
    if oldvfo == vfo:
      if is_band_down:
        d = -delta
      else:
        d = delta
    else:
      d = vfo - oldvfo
    self.VFO += d
    self.txFreq -= d
    self.rxFreq -= d
    # Set the display but do not change the hardware
    self.graph.SetVFO(self.VFO)
    self.waterfall.SetVFO(self.VFO)
    self.screen.SetTxFreq(self.txFreq, self.rxFreq)
    self.freqDisplay.Display(self.txFreq + self.VFO)
  def OnBtnDownBand(self, event):
    self.band_up_down = 1
    self.OnBtnUpDnBandDelta(event, True)
  def OnBtnUpBand(self, event):
    self.band_up_down = 1
    self.OnBtnUpDnBandDelta(event, False)
  def OnBtnUpDnBandDone(self, event):
    self.band_up_down = 0
    tune = self.txFreq
    vfo = self.VFO
    self.txFreq = self.VFO = 0		# Force an update
    self.ChangeHwFrequency(tune, vfo, 'BtnUpDown')
  def GetAmplPhase(self, is_tx):
    if conf.bandAmplPhase.has_key("panadapter"):
      band = "panadapter"
    else:
      band = self.lastBand
    try:
      if is_tx:
        lst = self.bandAmplPhase[band]["tx"]
      else:
        lst = self.bandAmplPhase[band]["rx"]
    except KeyError:
      return (0.0, 0.0)
    length = len(lst)
    if length == 0:
      return (0.0, 0.0)
    elif length == 1:
      return lst[0][2], lst[0][3]
    elif self.VFO < lst[0][0]:		# before first data point
      i1 = 0
      i2 = 1
    elif lst[length - 1][0] < self.VFO:	# after last data point
      i1 = length - 2
      i2 = length - 1
    else:
      # Binary search for the bracket VFO
      i1 = 0
      i2 = length
      index = (i1 + i2) / 2
      for i in range(length):
        diff = lst[index][0] - self.VFO
        if diff < 0:
          i1 = index
        elif diff > 0:
          i2 = index
        else:		# equal VFO's
          return lst[index][2], lst[index][3]
        if i2 - i1 <= 1:
          break
        index = (i1 + i2) / 2
    d1 = self.VFO - lst[i1][0]		# linear interpolation
    d2 = lst[i2][0] - self.VFO
    dx = d1 + d2
    ampl = (d1 * lst[i2][2] + d2 * lst[i1][2]) / dx
    phas = (d1 * lst[i2][3] + d2 * lst[i1][3]) / dx
    return ampl, phas
  def PostStartup(self):	# called once after sound attempts to start
    self.config_screen.OnGraphData(None)	# update config in case sound is not running
  def FldigiPoll(self):		# Keep Quisk and Fldigi frequencies equal; control PTT from Fldigi
    if self.fldigi_server is None:
      try:
        self.fldigi_server = ServerProxy(conf.digital_xmlrpc_url)
      except:
        # traceback.print_exc()
        return
    if self.fldigi_freq:	# Our frequency changed; send to fldigi
      try:
        self.fldigi_server.main.set_frequency(float(self.fldigi_freq))
      except:
        # traceback.print_exc()
        pass
      self.fldigi_freq = None
    else:
      try:
        freq = self.fldigi_server.main.get_frequency()
      except:
        # traceback.print_exc()
        pass
      else:
        freq = int(freq + 0.5)
        self.ChangeDisplayFrequency(freq - self.VFO, self.VFO)
    try:
      rxtx = self.fldigi_server.main.get_trx_status()	# returns rx, tx, tune
    except:
      return
    if QS.is_key_down():
      if rxtx == 'rx':
        self.fldigi_server.main.tx()
    else:	# key is up
      if rxtx != 'rx':
        self.fldigi_server.main.rx()
  def HamlibPoll(self):		# Poll for Hamlib commands
    if self.hamlib_socket:
      try:		# Poll for new client connections.
        conn, address = self.hamlib_socket.accept()
      except socket.error:
        pass
      else:
        # print 'Connection from', address
        self.hamlib_clients.append(HamlibHandler(self, conn, address))
      for client in self.hamlib_clients:	# Service existing clients
        if not client.Process():		# False return indicates a closed connection; remove the handler for this client
          self.hamlib_clients.remove(client)
          # print 'Remove', client.address
          break
  def OnReadSound(self):	# called at frequent intervals
    self.timer = time.time()
    if self.screen == self.scope:
      data = QS.get_graph(0, 1.0, 0)	# get raw data
      if data:
        self.scope.OnGraphData(data)			# Send message to draw new data
        return 1		# we got new graph/scope data
    else:
      data = QS.get_graph(1, self.zoom, float(self.zoom_deltaf))	# get FFT data
      if data:
        #T('')
        self.NewSmeter()			# update the S-meter
        if self.screen == self.graph:
          self.waterfall.OnGraphData(data)		# save waterfall data
          self.graph.OnGraphData(data)			# Send message to draw new data
        elif self.screen == self.config_screen:
          pass
        else:
          self.screen.OnGraphData(data)			# Send message to draw new data
        #T('graph data')
        #application.Yield()
        #T('Yield')
        return 1		# We got new graph/scope data
    if QS.get_overrange():
      self.clip_time0 = self.timer
      self.freqDisplay.Clip(1)
    if self.clip_time0:
      if self.timer - self.clip_time0 > 1.0:
        self.clip_time0 = 0
        self.freqDisplay.Clip(0)
    if self.timer - self.heart_time0 > 0.10:		# call hardware to perform background tasks
      self.heart_time0 = self.timer
      if self.screen == self.config_screen:
        self.screen.OnGraphData()			# Send message to draw new data
      Hardware.HeartBeat()
      if self.add_version and Hardware.GetFirmwareVersion() is not None:
        self.add_version = False
        self.config_text = "%s, firmware version 1.%d" % (self.config_text, Hardware.GetFirmwareVersion())
      if not self.band_up_down:
        # Poll the hardware for changed frequency.  This is used for hardware
        # that can change its frequency independently of Quisk; eg. K3.
        tune, vfo = Hardware.ReturnFrequency()
        if tune is not None and vfo is not None:
          self.BandFromFreq(tune)
          self.ChangeDisplayFrequency(tune - vfo, vfo)
        if conf.digital_output_name and self.mode == 'DGTL':		# Poll Fldigi for changed frequency
          self.FldigiPoll()
        self.HamlibPoll()
      if self.timer - self.save_time0 > 20.0:
        self.save_time0 = self.timer
        if self.CheckState():
          self.SaveState()
      if self.tmp_playing and QS.set_record_state(-1):	# poll to see if playback is finished
        self.btnTmpPlay.SetValue(False, True)

def main():
  """If quisk is installed as a package, you can run it with quisk.main()."""
  App()
  application.MainLoop()

if __name__ == '__main__':
  main()

