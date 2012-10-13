# This is the hardware file from my shack, which controls various hardware.
# The files to control my 2010 transceiver and for the improved version HiQSDR
# are in the package directory HiQSDR.

from hiqsdr.quisk_hardware import Hardware as BaseHw
from n2adr import station_hardware

class Hardware(BaseHw):
  def __init__(self, app, conf):
    BaseHw.__init__(self, app, conf)
    self.use_sidetone = 1
    self.vfo_frequency = 0		# current vfo frequency
    self.rf_gain_labels = ('RF 0 dB', 'RF +16', 'RF -20', 'RF -10')
    # Other hardware
    self.anttuner = station_hardware.AntennaTuner(app, conf)	# Control the antenna tuner
    self.lpfilter = station_hardware.LowPassFilter(app, conf)	# Control LP filter box
    self.hpfilter = station_hardware.HighPassFilter(app, conf)	# Control HP filter box
  def open(self):
    self.anttuner.open()
    return BaseHw.open(self)
  def close(self):
    self.anttuner.close()
    return BaseHw.close(self)
  def OnAntTuner(self, text):	# One of the tuner buttons was pressed
    self.anttuner.OnAntTuner(text)
  def ChangeFilterFrequency(self, tx_freq):
    # Change the filters but not the receiver; used for panadapter
    if tx_freq and tx_freq > 0:
      self.anttuner.SetTxFreq(tx_freq)
      self.lpfilter.SetTxFreq(tx_freq)
      self.hpfilter.SetTxFreq(tx_freq)
  def ChangeFrequency(self, tx_freq, vfo_freq, source='', band='', event=None):
    self.ChangeFilterFrequency(tx_freq)
    return BaseHw.ChangeFrequency(self, tx_freq, vfo_freq, source, band, event)
  def ChangeBand(self, band):
    # band is a string: "60", "40", "WWV", etc.
    self.anttuner.ChangeBand(band)
    self.lpfilter.ChangeBand(band)
    self.hpfilter.ChangeBand(band)
    if band == '40':
      self.correct_smeter = 20.5
    else:
      self.correct_smeter = 20.5
    return BaseHw.ChangeBand(self, band)
  def HeartBeat(self):	# Called at about 10 Hz by the main
    self.anttuner.HeartBeat()
    self.lpfilter.HeartBeat()
    self.hpfilter.HeartBeat()
    return BaseHw.HeartBeat(self)
  def OnSpot(self, level):
    self.anttuner.OnSpot(level)
    return BaseHw.OnSpot(self, level)
  def OnButtonRfGain(self, event):
    self.hpfilter.OnButtonRfGain(event)

