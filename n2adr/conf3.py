# This is a config file to test the microphone by playing microphone
# sound instead of radio sound.
# The PTT button must be pressed, and the tune must be at zero.

import sys
from quisk_hardware_model import Hardware as BaseHardware
import _quisk as QS

if sys.platform == "win32":
  name_of_sound_capt = "Primary"
  name_of_sound_play = ''
  microphone_name    = "Microphone"
  name_of_mic_play = "Primary"
  latency_millisecs = 150
  data_poll_usec = 10000
elif 1:
  name_of_sound_capt = 'portaudio:Analog'
  name_of_sound_play = ''
  microphone_name = "portaudio:AK5370"
  name_of_mic_play = 'portaudio:Analog'
  latency_millisecs = 150
  data_poll_usec = 5000
else:
  name_of_sound_capt = 'hw:0'
  name_of_sound_play = ''
  microphone_name = "alsa:AK5370"
  name_of_mic_play = 'hw:0'
  latency_millisecs = 50
  data_poll_usec = 5000

add_fdx_button = 1
sample_rate = 48000
mic_playback_rate = 48000
mic_sample_rate = 48000
mic_out_volume = 0.7

mic_clip = 3.0
mic_preemphasis = 0.6

if microphone_name:
  mixer_settings = [
    (microphone_name, 2, 0.80),		# numid of microphone volume control, volume 0.0 to 1.0;
    (microphone_name, 1, 1.0)		# numid of capture on/off control, turn on with 1.0;
  ]

class Hardware(BaseHardware):
  def OnButtonPTT(self, event):
    if event.GetEventObject().GetValue():
      QS.set_key_down(1)
    else:
      QS.set_key_down(0)
