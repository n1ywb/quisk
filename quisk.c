#include <Python.h>
#include <stdlib.h>
#include <math.h>
#include <complex.h>	// Use native C99 complex type for fftw3
#include <fftw3.h>
#include <sys/types.h>

#ifdef MS_WINDOWS
#include <Winsock2.h>
#define QUISK_SHUT_RD	SD_RECEIVE
#define QUISK_SHUT_BOTH	SD_BOTH
#else
#include <sys/socket.h>
#include <arpa/inet.h>
#define INVALID_SOCKET	-1
#define QUISK_SHUT_RD	SHUT_RD
#define QUISK_SHUT_BOTH	SHUT_RDWR
#endif

#include "quisk.h"
#include "filter.h"

#define DEBUG		0

#define FM_FILTER_DEMPH		300.0		// Frequency of FM lowpass de-emphasis filter

static int fft_error;			// fft error count
static int count_fft;			// how many fft's have occurred (for average)
enum fft_status {EMPTY,			// fft_data is currently unused
	FILLING,			// now writing samples to this fft
	READY};				// ready to perform fft
typedef struct fftd {
	fftw_complex * samples;		// complex data for fft
	fftw_plan plan;			// fft plan for fftW
	int index;			// position of next fft sample
	enum fft_status status;		// whether the fft is busy
	struct fftd * next;			// the next data block to use
} fft_data;
static fft_data * FFT1, * FFT2, * FFT3;	// data for three fft's		WB4JFI ADD third FFT
static fft_data * ptWriteFft;		// Write the current samples to this fft
static double * fft_avg;		// Array to average the FFT
static double * fft_window;		// Window for FFT data
static double * current_graph;	// current graph data as returned
static int use_remove_dc=1;		// Remove DC from samples

static PyObject * QuiskError;		// Exception for this module
static PyObject * pyApp;		// Application instance
static int fft_size;			// size of fft, e.g. 1024
int data_width;				// number of points to return as graph data; fft_size * n
int rxMode;				// 0 to 7, 10 to 12: CWL, CWU, LSB, USB, AM, FM, EXT, DGTL, IMD(10 to 12)
int quisk_noise_blanker;		// noise blanker level, 0 for off
PyObject * quisk_pyConfig=NULL;	// Configuration module instance
long quisk_mainwin_handle;		// Handle of the main window
static int sample_rate=1;		// Sample rate such as 48000, 96000, 192000
static int graphX;			// Origin of first X value for graph data
static int graphY;			// Origin of 0 dB for graph data
static int average_count;		// Number of FFT's to average for graph
static double graphScale;		// Scale factor for graph
static complex testtonePhase;		// Phase increment for test tone
static double audioVolume;		// Audio output level, 0.0 to 1.0
static complex tunePhase;		// Phase increment for tuning frequency
static double cFilterI[MAX_FILTER_SIZE];	// Digital filter coefficients for receive
static double cFilterQ[MAX_FILTER_SIZE];	// Digital filter coefficients
static double bufFilterI[MAX_FILTER_SIZE];	// Digital filter sample buffer
static double bufFilterQ[MAX_FILTER_SIZE];	// Digital filter sample buffer
static complex bufFilterC[MAX_FILTER_SIZE];	// Digital filter sample buffer
static int sizeFilter;			// Number of coefficients for filters
static int indexFilter;			// Index of current filter data in buffer
static int isFDX;			// Are we in full duplex mode?
static int filter_bandwidth;		// Current filter bandwidth in Hertz

static double sidetoneVolume;		// Audio output level of the CW sidetone, 0.0 to 1.0
static int keyupDelay;			// Play silence after sidetone ends
static complex sidetonePhase;		// Phase increment for sidetone
int quisk_sidetoneCtrl;			// sidetone control value 0 to 1000

static int agcInUse;			// 0 for no AGC
static double agcRelease, agcLevel;	// AGC parameters
static double agcMaxGain;		// Max AGC gain
static double agcOffGain;		// Gain when AGC is off
static double squelch_level;		// setting of squelch control
static int quisk_invert_spectrum = 0;	// Invert the input RF spectrum

static double Smeter;			// Measured RMS signal strength
static int rx_tune_freq;		// Receive tuning frequency as +/- sample_rate / 2
int quisk_tx_tune_freq;			// Transmit tuning frequency as +/- sample_rate / 2
static int rit_freq;					// RIT frequency in Hertz

#define RX_UDP_SIZE		1442		// Expected size of UDP samples packet
static int rx_udp_socket = INVALID_SOCKET;		// Socket for receiving ADC samples from UDP
static int rx_udp_started = 0;		// Have we received any data yet?
int quisk_using_udp = 0;			// Are we using rx_udp_socket?
static double rx_udp_gain_correct = 0;		// For decimation by 5, correct by 4096 / 5**5
static double rx_udp_clock;			// Clock frequency for UDP samples
static int rx_udp_read_blocks = 0;	// Number of blocks to read for each read call

static int is_little_endian;		// Test byte order; is it little-endian?

enum quisk_rec_state quisk_record_state = IDLE;
static float * quisk_record_buffer;
static int quisk_record_bufsize;
static int quisk_record_index;
static int quisk_play_index;
static int quisk_mic_index;
static int quisk_record_full;

static int fDecimate(double * dSamples, int nSamples, double fdecim)
{
	int i, nout;
	double xm0, xm1, xm2, xm3;
	static double dindex = 1;
	static double y0=0, y1=0, y2=0, y3=0;
	static int in=0, out=0;

	in += nSamples;
	nout = 0;
	for (i = 0; i < nSamples; i++) {
		y3 = dSamples[i];
		if (dindex < 1 || dindex >= 2.2)
			printf ("dindex %.5f  fdecim %.8f\n", dindex, fdecim);
		if (dindex < 2) {
#if 0
				dSamples[nout++] = (1 - (dindex - 1)) * y1 + (dindex - 1) * y2;
#else
				xm0 = dindex - 0;
				xm1 = dindex - 1;
				xm2 = dindex - 2;
				xm3 = dindex - 3;
				dSamples[nout++] = xm1 * xm2 * xm3 * y0 / -6.0 + xm0 * xm2 * xm3 * y1 / 2.0 +
					xm0 * xm1 * xm3 * y2 / -2.0 + xm0 * xm1 * xm2 * y3 / 6.0;
#endif
			out++;
			dindex += fdecim - 1;
			y0 = y1;
			y1 = y2;
			y2 = y3;
		}
		else {
			if (dindex > 2.3) printf ("Skip at %.2f\n", dindex);
			y0 = y1;
			y1 = y2;
			y2 = y3;
			dindex -= 1;
		}
	}
	//printf ("in %d out %d\n", in, out);
	return nout;
}
			
#define QUISK_NB_HWINDOW_SECS	500.E-6	// half-size of blanking window in seconds
static void NoiseBlanker(complex * cSamples, int nSamples)
{
	static complex * cSaved = NULL;
	static double  * dSaved = NULL;
	static double save_sum;
	static int save_size, hwindow_size, state, index, win_index;
	static int sample_rate = -1;
	int i, j, k, is_pulse;
	double mag, limit;
	complex samp;
#if DEBUG
	static time_t time0 = 0;
	static int debug_count = 0;
#endif

	if (quisk_noise_blanker <= 0)
		return;
	if (quisk_sound_state.sample_rate != sample_rate) {	// Initialization
		sample_rate = quisk_sound_state.sample_rate;
		state = 0;
		index = 0;
		win_index = 0;
		save_sum = 0.0;
		hwindow_size = (int)(sample_rate * QUISK_NB_HWINDOW_SECS + 0.5);
		save_size = hwindow_size * 3;	// number of samples in the average
		i = save_size * sizeof(double);
		dSaved = (double *) realloc(dSaved, i);
		memset (dSaved, 0, i);
		i = save_size * sizeof(complex);
		cSaved = (complex *)realloc(cSaved, i);
		memset (cSaved, 0, i);
#if DEBUG
		printf ("Noise blanker: save_size %d  hwindow_size %d\n",
			save_size, hwindow_size);
#endif
	}
	switch(quisk_noise_blanker) {
	case 1:
	default:
		limit = 6.0;
		break;
	case 2:
		limit = 4.0;
		break;
	case 3:
		limit = 2.5;
		break;
	}
	for (i = 0; i < nSamples; i++) {
		// output oldest sample, save newest
		samp = cSamples[i];				// newest sample
		cSamples[i] = cSaved[index];	// oldest sample
		cSaved[index] = samp;
		// use newest sample
		mag = cabs(samp);
		save_sum -= dSaved[index];	// remove oldest sample magnitude
		dSaved[index] = mag;		// save newest sample magnitude
		save_sum += mag;			// update sum of samples
		if (mag <= save_sum / save_size * limit)	// see if we have a large pulse
			is_pulse = 0;
		else
			is_pulse = 1;
		switch (state) {
		case 0:		// Normal state
			if (is_pulse) {		// wait for a pulse
				state = 1;
				k = index;
				for (j = 0; j < hwindow_size; j++) {	// apply window to prior samples
					cSaved[k--] *= (double)j / hwindow_size;
					if (k < 0)
						k = save_size - 1;
				}
			}
			else if (win_index) {		// pulses have stopped, increase window to 1.0
				cSaved[index] *= (double)win_index / hwindow_size;
				if (++win_index >= hwindow_size)
					win_index = 0;	// no more window
			}
			break;
		case 1:		// we got a pulse
			cSaved[index] = 0;	// zero samples until the pulses stop
			if ( ! is_pulse) {
				// start raising the window, but be prepared to window another pulse
				state = 0;
				win_index = 1;
			}
			break;
		}
#if DEBUG
		if (debug_count) {
			printf ("%d", is_pulse);
			if (--debug_count == 0)
				printf ("\n");
		}
		else if (is_pulse && time(NULL) != time0) {
			time0 = time(NULL);
			debug_count = hwindow_size * 2;
			printf ("%d", is_pulse);
		}
#endif
		if (++index >= save_size)
			index = 0;
	}
	return;
}

static complex dRxFilterOut(complex sample)
{
	complex cx;
	int j, k;

	if ( ! sizeFilter)
		return sample;
	bufFilterC[indexFilter] = sample;
	cx = 0;
	j = indexFilter;
	for (k = 0; k < sizeFilter; k++) {
		cx += bufFilterC[j] * cFilterI[k];
		if (++j >= sizeFilter)
			j = 0;
	}
	if (++indexFilter >= sizeFilter)
		indexFilter = 0;
	return cx;
}

static complex cRxFilterOut(complex sample)
{
	double accI, accQ;
	int j, k;

	if ( ! sizeFilter)
		return sample;
	bufFilterI[indexFilter] = creal(sample);
	bufFilterQ[indexFilter] = cimag(sample);
	accI = accQ = 0;
	j = indexFilter;
	for (k = 0; k < sizeFilter; k++) {
		accI += bufFilterI[j] * cFilterI[k];
		accQ += bufFilterQ[j] * cFilterQ[k];
		if (++j >= sizeFilter)
			j = 0;
	}
	if (++indexFilter >= sizeFilter)
		indexFilter = 0;
	return accI + I * accQ;
}

static void AddTestTone(complex * cSamples, int nSamples)
{
	int i;
	static complex testtoneVector = 21474836.47;	// -40 dB
	static complex audioVector = 1.0;
	complex audioPhase;

	switch (rxMode) {
	default:
		//testtonePhase = cexp(I * 2 * M_PI * (quisk_sidetoneCtrl - 500) / 1000.0);
		for (i = 0; i < nSamples; i++) {
			cSamples[i] += testtoneVector;
			testtoneVector *= testtonePhase;
		}
		break;
	case 4:		// AM
		//audioPhase = cexp(I * 2 * M_PI * quisk_sidetoneCtrl * 5 / sample_rate);
		audioPhase = cexp(I * 2.0 * M_PI * 1000 / sample_rate);
		for (i = 0; i < nSamples; i++) {
			cSamples[i] += testtoneVector * (1.0 + creal(audioVector));
			testtoneVector *= testtonePhase;
			audioVector *= audioPhase;
		}
		break;
	case 5:		 // FM
		//audioPhase = cexp(I * 2 * M_PI * quisk_sidetoneCtrl * 5 / sample_rate);
		audioPhase = cexp(I * 2.0 * M_PI * 1000 / sample_rate);
		for (i = 0; i < nSamples; i++) {
			cSamples[i] += testtoneVector * cexp(I * creal(audioVector));
			testtoneVector *= testtonePhase;
			audioVector *= audioPhase;
		}
		break;
	}
}

static int IsSquelch(int freq)
{  // measure the signal level for squelch
	int i, i1, i2, width;
	double meter;

	width = 5000 * data_width / sample_rate;	// bandwidth determines number of pixels to average
	i1 = (int)((double)freq * data_width / sample_rate + data_width / 2.0 - width / 2.0 + 0.5);
	i2 = i1 + width;
	meter = 0;
	if (i1 >= 0 && i2 < data_width) {	// too close to edge?
		for (i = i1; i < i2; i++) {
			meter += current_graph[i];
		}
	}
	meter /= width;
	if (meter == 0 || meter < squelch_level)
		return 1;   // meter == 0 means Rx freq is off-screen so squelch is on
	else
		return 0;
}

static PyObject * set_record_state(PyObject * self, PyObject * args)
{  // called when a Record or Play button is pressed, or with -1 to poll
	int button;

	if (!PyArg_ParseTuple (args, "i", &button))
		return NULL;
	switch (button) {
	case 0:			// press record
		if ( ! quisk_record_buffer) {	// initialize
			quisk_record_bufsize = (int)(QuiskGetConfigDouble("max_record_minutes", 0.25) * quisk_sound_state.playback_rate * 60.0 + 0.2);
			quisk_record_buffer = (float *)malloc(sizeof(float) * quisk_record_bufsize);
		}
		quisk_record_index = 0;
		quisk_play_index = 0;
		quisk_mic_index = 0;
		quisk_record_full = 0;
		quisk_record_state = RECORD;
		break;
	case 1:			// release record
		quisk_record_state = IDLE;
		break;
	case 2:			// press play
		if (quisk_record_full) {
			quisk_play_index = quisk_record_index + 1;
			if (quisk_play_index >= quisk_record_bufsize)
				quisk_play_index = 0;
		}
		else {
			quisk_play_index = 0;
		}
		quisk_mic_index = quisk_play_index;
		quisk_record_state = PLAYBACK;
		break;
	case 3:			// release play
		quisk_record_state = IDLE;
		break;
	}
	return PyInt_FromLong(quisk_record_state != PLAYBACK);
}

static void tmp_record(complex * cSamples, int nSamples, double agcGain)		// save radio sound
{
	int i;

	for (i = 0; i < nSamples; i++) {
		quisk_record_buffer[quisk_record_index++] = creal(cSamples[i]) * agcGain;
		if (quisk_record_index >= quisk_record_bufsize) {
			quisk_record_index = 0;
			quisk_record_full = 1;
		}
	}
}

static void tmp_playback(complex * cSamples, int nSamples, double volume)
{  // replace radio sound with saved sound
	int i;
	double d;

	for (i = 0; i < nSamples; i++) {
		d = quisk_record_buffer[quisk_play_index++] * volume;
		cSamples[i] = d + I * d;
		if (quisk_play_index >= quisk_record_bufsize)
			quisk_play_index = 0;
		if (quisk_play_index == quisk_record_index) {
			quisk_record_state = IDLE;
			return;
		}
	}
}

void quisk_tmp_microphone(complex * cSamples, int nSamples)
{  // replace microphone samples with saved sound
	int i;
	double d;

	for (i = 0; i < nSamples; i++) {
		d = quisk_record_buffer[quisk_mic_index++];
		cSamples[i] = d + I * d;
		if (quisk_mic_index >= quisk_record_bufsize)
			quisk_mic_index = 0;
		if (quisk_mic_index == quisk_record_index) {
			quisk_record_state = IDLE;
			return;
		}
	}
}

int quisk_process_samples(complex * cSamples, int nSamples)
{
// Called when samples are available.
// Samples range from about 2^16 to a max of 2^31.
	int i, nout, filter_srate, is_key_down, interp, final_filter;
	double d, di, agc_level, agcPeak;
	double double_filter_decim;
	complex cx, cpx;
	double dsamples[SAMP_BUFFER_SIZE];

	static double FM_www, FM_nnn, FM_a_0, FM_a_1, FM_b_1, FM_x_1, FM_y_1;   // filter for FM
	static double agcGain;			// Volume level control for audio output
	static complex tuneVector = 1;
	static complex sidetoneVector = BIG_VOLUME;
	static double dOutCounter = 0;		// Cumulative net output samples for sidetone etc.
	static int sidetoneIsOn = 0;		// The status of the sidetone
	static double sidetoneEnvelope;		// Shape the rise and fall times of the sidetone
	static double keyupEnvelope = 1.0;	// Shape the rise time on key up
	static int playSilence;
	static int is_squelch = 0;		// Are we squelched?
	static complex fm_1 = 10;		// Sample delayed by one
	static double dc_remove;		// DC removal for AM
	static struct quisk_cHB45Filter HalfBand1 = {NULL, 0, 0};
	static struct quisk_cHB45Filter HalfBand2 = {NULL, 0, 0};
	static struct quisk_cHB45Filter HalfBand3 = {NULL, 0, 0};
	static struct quisk_cHB45Filter HalfBand4 = {NULL, 0, 0};
	static struct quisk_cHB45Filter HalfBand5 = {NULL, 0, 0};
	static struct quisk_dHB45Filter HalfBand6 = {NULL, 0, 0};
	static struct quisk_dHB45Filter HalfBand7 = {NULL, 0, 0};
	static struct quisk_dHB45Filter HalfBand8 = {NULL, 0, 0};
	static struct quisk_dHB45Filter HalfBand9 = {NULL, 0, 0};
	static struct quisk_cFilter filtSdriq2 = {NULL};
	static struct quisk_cFilter filtSdriq4;
	static struct quisk_cFilter filtSdriq5;
	static struct quisk_cFilter filtSdriq7;
	static struct quisk_cFilter filtDecim5;
	static struct quisk_cFilter filtDecim48to24;
	static struct quisk_dFilter filtAudio24p3;
	static struct quisk_dFilter filtAudio24p4;
	static struct quisk_dFilter filtAudio12p2;
	static struct quisk_dFilter filtAudio24p6;
	static struct quisk_dFilter filtAudioFmHp;

#if DEBUG
	static int printit;
	static time_t time0;
	static double levelA=0, levelB=0, levelC=0, levelD=0, levelE=0;

	if (time(NULL) != time0) {
		time0 = time(NULL);
		printit = 1;
	}
	else {
		printit = 0;
	}
#endif
	if ( ! filtSdriq2.dCoefs) {	// Initialize all filters
		quisk_filt_cInit(&filtSdriq2, quiskFilt53D2Coefs, sizeof(quiskFilt53D2Coefs)/sizeof(double));
		quisk_filt_cInit(&filtSdriq4, quiskFilt111D4Coefs, sizeof(quiskFilt111D4Coefs)/sizeof(double));
		quisk_filt_cInit(&filtSdriq5, quiskFilt133D5Coefs, sizeof(quiskFilt133D5Coefs)/sizeof(double));
		quisk_filt_cInit(&filtSdriq7, quiskFilt185D7Coefs, sizeof(quiskFilt185D7Coefs)/sizeof(double));
		quisk_filt_cInit(&filtDecim5, quiskFilt240D5Coefs, sizeof(quiskFilt240D5Coefs)/sizeof(double));
		quisk_filt_cInit(&filtDecim48to24, quiskFilt48dec24Coefs, sizeof(quiskFilt48dec24Coefs)/sizeof(double));
		quisk_filt_dInit(&filtAudio24p3,  quiskAudio24p3Coefs, sizeof(quiskAudio24p3Coefs)/sizeof(double));
		quisk_filt_dInit(&filtAudio24p4,  quiskAudio24p4Coefs, sizeof(quiskAudio24p4Coefs)/sizeof(double));
		quisk_filt_dInit(&filtAudio12p2, quiskAudio24p4Coefs, sizeof(quiskAudio24p4Coefs)/sizeof(double));
		quisk_filt_dInit(&filtAudio24p6, quiskAudio24p6Coefs, sizeof(quiskAudio24p6Coefs)/sizeof(double));
		quisk_filt_dInit(&filtAudioFmHp, quiskAudioFmHpCoefs, sizeof(quiskAudioFmHpCoefs)/sizeof(double));
		FM_www = tan(M_PI * FM_FILTER_DEMPH / 24000);   // filter for FM
		FM_nnn = 1.0 / (1.0 + FM_www);
		FM_a_0 = FM_www * FM_nnn;
		FM_a_1 = FM_a_0;
		FM_b_1 = FM_nnn * (FM_www - 1.0);
		//printf ("dsamples[i] = y_1 = di * %12.6lf + x_1 * %12.6lf - y_1 * %12.6lf\n", FM_a_0, FM_a_1, FM_b_1);
	}
	if (nSamples <= 0)
		return nSamples;
	is_key_down = quisk_is_key_down();

	if (is_key_down && !isFDX) {	// The key is down; replace this data block
		dOutCounter += (double)nSamples * quisk_sound_state.playback_rate /
				quisk_sound_state.sample_rate;
		nout = (int)dOutCounter;			// number of samples to output
		dOutCounter -= nout;
		playSilence = keyupDelay;
		keyupEnvelope = 0;
		if (rxMode == 0 || rxMode == 1) {	// Play sidetone instead of radio for CW
			if (! sidetoneIsOn) {			// turn on sidetone
				sidetoneIsOn = 1;
				sidetoneEnvelope = 0;
				sidetoneVector = BIG_VOLUME;
			}
			for (i = 0 ; i < nout; i++) {
				if (sidetoneEnvelope < 1.0) {
					sidetoneEnvelope += 1. / (quisk_sound_state.playback_rate * 5e-3);	// 5 milliseconds
					if (sidetoneEnvelope > 1.0)
						sidetoneEnvelope = 1.0;
				}
				d = creal(sidetoneVector) * sidetoneVolume * sidetoneEnvelope;
				cSamples[i] = d + I * d;
				sidetoneVector *= sidetonePhase;
			}
		}
		else {			// Otherwise play silence
			for (i = 0 ; i < nout; i++)
				cSamples[i] = 0;
		}
		return nout;
	}
	// Key is up
	if(sidetoneIsOn) {		// decrease sidetone until it is off
		dOutCounter += (double)nSamples * quisk_sound_state.playback_rate /
				quisk_sound_state.sample_rate;
		nout = (int)dOutCounter;			// number of samples to output
		dOutCounter -= nout;
		for (i = 0; i < nout; i++) {
			sidetoneEnvelope -= 1. / (quisk_sound_state.playback_rate * 5e-3);	// 5 milliseconds
			if (sidetoneEnvelope < 0) {
				sidetoneIsOn = 0;
				sidetoneEnvelope = 0;
				break;		// sidetone is zero
			}
			d = creal(sidetoneVector) * sidetoneVolume * sidetoneEnvelope;
			cSamples[i] = d + I * d;
			sidetoneVector *= sidetonePhase;
		}
		for ( ; i < nout; i++) {	// continue with playSilence, even if zero
			cSamples[i] = 0;
			playSilence--;
		}
		return nout;
	}
	if (playSilence > 0) {		// Continue to play silence after the key is up
		dOutCounter += (double)nSamples * quisk_sound_state.playback_rate /
				quisk_sound_state.sample_rate;
		nout = (int)dOutCounter;			// number of samples to output
		dOutCounter -= nout;
		for (i = 0; i < nout; i++)
			cSamples[i] = 0;
		playSilence -= nout;
		return nout;
	}
	// We are done replacing sound with a sidetone or silence.  Filter and
	// demodulate the samples as radio sound.

	// Add a test tone to the data
	if (testtonePhase)
		AddTestTone(cSamples, nSamples);

	// Invert spectrum
	if (quisk_invert_spectrum) {
		for (i = 0; i < nSamples; i++) {
			cSamples[i] = conj(cSamples[i]);
			}
	}

	NoiseBlanker(cSamples, nSamples);

	// Check for space, then put samples into the fft input array.
	// Thanks to WB4JFI for the code to add a third FFT buffer, July 2010 (but changed to linked list).
	if (ptWriteFft->status == EMPTY) {
		ptWriteFft->status = FILLING;
		ptWriteFft->index = 0;
	}
	if (ptWriteFft->status == FILLING) {		// write samples to fft data array
		for (i = 0; i < nSamples; i++) {
			ptWriteFft->samples[ptWriteFft->index] = cSamples[i];
			if (++(ptWriteFft->index) >= fft_size) {	// check sample count
				ptWriteFft->status = READY;				// ready to run fft
				ptWriteFft = ptWriteFft->next;			// next data block
				if (ptWriteFft->status == EMPTY) {	// continue writing samples
					ptWriteFft->status = FILLING;
					ptWriteFft->index = 0;
				}
				else {				// no place to write samples
					fft_error++;
					break;
				}
			}
		}
	}

	// No need to tune and demodulate if we don't play sound
	if (quisk_sound_state.dev_play_name[0] == 0)
		return 0;
	// Tune the data to frequency
	if (tunePhase) {
		for (i = 0; i < nSamples; i++) {
			cSamples[i] *= tuneVector;
			tuneVector *= tunePhase;
		}
	}

	if (rxMode == 6) {		// External filter and demodulate
		d = (double)quisk_sound_state.sample_rate / quisk_sound_state.playback_rate;	// total decimation needed
		nSamples = quisk_extern_demod(cSamples, nSamples, d);
		// Find the peak signal amplitude
		agcPeak = 0;
		for (i = 0; i < nSamples; i++) {
			di = creal(cSamples[i]);
			if (agcPeak < di)
				agcPeak = di;
			di = cimag(cSamples[i]);
			if (agcPeak < di)
				agcPeak = di;
		}
		goto start_agc;
	}

	// Perhaps write sample data to the soundcard output without decimation
	if (TEST_AUDIO == 1) {		// Copy I channel capture to playback
		di = 1.e4 * audioVolume;
		for (i = 0; i < nSamples; i++)
			cSamples[i] = creal(cSamples[i]) * di;
		return nSamples;
	}
	else if (TEST_AUDIO == 2) {	// Copy Q channel capture to playback
		di = 1.e4 * audioVolume;
		for (i = 0; i < nSamples; i++)
			cSamples[i] = cimag(cSamples[i]) * di;
		return nSamples;
	}
#if DEBUG
	for (i = 0; i < nSamples; i++) {
		d = cabs(cSamples[i]);
		if (levelA < d)
			levelA = d;
	}
#endif

	// Decimate: Lower the sample rate to 24000 sps (or approx).  Filters are designed for
	// a pass bandwidth of 10 kHz and a stop bandwidth of 12 kHz.
	final_filter = rxMode == 4 || rxMode == 5;	// Use sharp FIR final filter for decimate by 2
	double_filter_decim = 1.0;
	switch((quisk_sound_state.sample_rate + 100) / 1000) {
	case 24:
		break;
	case 41:
	case 48:
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 53:	// SDR-IQ
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtSdriq2, 2);
		double_filter_decim = quisk_sound_state.sample_rate / 2.0 / 24000.0;
		break;
	case 96:
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand1);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 111:	// SDR-IQ
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtSdriq4, 4);
		double_filter_decim = quisk_sound_state.sample_rate / 4.0 / 24000.0;
		break;
	case 133:	// SDR-IQ
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtSdriq5, 5);
		double_filter_decim = quisk_sound_state.sample_rate / 5.0 / 24000.0;
		break;
	case 185:	// SDR-IQ
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtSdriq7, 7);
		double_filter_decim = quisk_sound_state.sample_rate / 7.0 / 24000.0;
		break;
	case 192:
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand1);
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand2);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 240:
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim5, 5);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 384:
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand1);
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand2);
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand3);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 480:
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand1);
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim5, 5);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	case 960:
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand1);
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand2);
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim5, 5);
		if (final_filter)
			nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		else
			nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand5);
		break;
	default:
		printf ("Failure in quisk.c in integer decimation\n");
		break;
	}

#if DEBUG
	for (i = 0; i < nSamples; i++) {
		d = cabs(cSamples[i]);
		if (levelB < d)
			levelB = d;
	}
#endif

	// Filter and demodulate signal, copy capture buffer cSamples to play buffer dsamples.
	// filter_srate is the sample rate after integer decimation.
	filter_srate = 24000;
	switch(rxMode) {
	case 0:		// lower sideband CW at 6 ksps
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand4);
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		for (i = 0; i < nSamples; i++) {
			cx = cRxFilterOut(cSamples[i]);
			dsamples[i] = creal(cx) + cimag(cx);
		}
		nSamples = quisk_dInterpolate(dsamples, nSamples, &filtAudio12p2, 2);
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand6);
		break;
	case 1:		// upper sideband CW at 6 ksps
		nSamples = quisk_cDecim2HB45(cSamples, nSamples, &HalfBand4);
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		for (i = 0; i < nSamples; i++) {
			cx = cRxFilterOut(cSamples[i]);
			dsamples[i] = creal(cx) - cimag(cx);
		}
		nSamples = quisk_dInterpolate(dsamples, nSamples, &filtAudio12p2, 2);
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand6);
		break;
	case 2:	 // lower sideband SSB at 12 ksps
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		for (i = 0; i < nSamples; i++) {
			cx = cRxFilterOut(cSamples[i]);
			dsamples[i] = creal(cx) + cimag(cx);
		}
		nSamples = quisk_dInterpolate(dsamples, nSamples, &filtAudio24p4, 2);
		break;
	case 3:	 // upper sideband SSB at 12 ksps
	case 7:
	default:
		nSamples = quisk_cDecimate(cSamples, nSamples, &filtDecim48to24, 2);
		for (i = 0; i < nSamples; i++) {
			cx = cRxFilterOut(cSamples[i]);
			dsamples[i] = creal(cx) - cimag(cx);
		}
		nSamples = quisk_dInterpolate(dsamples, nSamples, &filtAudio24p4, 2);
		break;
	case 4:		// AM at 24 ksps
		for (i = 0; i < nSamples; i++) {
			cx = dRxFilterOut(cSamples[i]);
			di = cabs(cx);
			d = di + dc_remove * 0.99;	// DC removal; R.G. Lyons page 553
			di = d - dc_remove;
			dc_remove = d;
			dsamples[i] = di;
		}
		nSamples = quisk_dFilter(dsamples, nSamples, &filtAudio24p6);
		break;
	case 5:		// FM at 24 ksps
		for (i = 0; i < nSamples; i++) {
			cx = dRxFilterOut(cSamples[i]);
			cpx = cx * conj(fm_1);
			fm_1 = cx;
			di = filter_srate * carg(cpx);
			// FM de-emphasis
			dsamples[i] = FM_y_1 = di * FM_a_0 + FM_x_1 * FM_a_1 - FM_y_1 * FM_b_1;
			FM_x_1 = di;
		}
		nSamples = quisk_dDecimate(dsamples, nSamples, &filtAudio24p3, 2);
		nSamples = quisk_dFilter(dsamples, nSamples, &filtAudioFmHp);
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand6);
		break;
	}
#if DEBUG
	for (i = 0; i < nSamples; i++) {
		d = fabs(dsamples[i]);
		if (levelC < d)
			levelC = d;
	}
#endif

	// Perhaps decimate by an additional fraction
	if (double_filter_decim != 1.0)
		nSamples = fDecimate(dsamples, nSamples, double_filter_decim);
#if DEBUG
	for (i = 0; i < nSamples; i++) {
		d = fabs(dsamples[i]);
		if (levelD < d)
			levelD = d;
	}
#endif
	// Interpolate the samples back to the play rate
	interp = quisk_sound_state.playback_rate / filter_srate;
	if (interp > 1) {
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand7);
		interp /= 2;
	}
	if (interp > 1) {
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand8);
		interp /= 2;
	}
	if (interp > 1) {
		nSamples = quisk_dInterp2HB45(dsamples, nSamples, &HalfBand9);
		interp /= 2;
	}
	if (interp != 1)
		printf ("Failure in quisk.c in integer interpolation\n");
#if DEBUG
	for (i = 0; i < nSamples; i++) {
		d = fabs(dsamples[i]);
		if (levelE < d)
			levelE = d;
	}
#endif
	// Find the peak signal amplitude, copy sound to output cSamples
	agcPeak = 0;
	for (i = 0; i < nSamples; i++) {
		d = dsamples[i];
		cSamples[i] = d + I * d;	// monophonic sound, two channels
		d = fabs(d);
		if (agcPeak < d)
			agcPeak = d;
	}
start_agc:
	// Normalize peak amplitude to 1.0 maximum
	if (agcPeak < 2E3)
		agcPeak = 2E3 / CLIP32;
	else
		agcPeak /= CLIP32;
	// Change volume using automatic gain control, AGC.
	// The maximum signal is about 2^31, namely 2e9.
	// This is the change fraction di, maximum 1
	di = (double)nSamples / quisk_sound_state.playback_rate / agcRelease;
	if (di > 1.0)
		di = 1.0;
	// The current output if agcGain is not changed is agcPeak * agcGain
	if (rxMode == 5) {		// mode is FM
		// Brick wall agc; make all signals the same volume
		if (agcPeak * agcGain >= 1.0)	// clipping
			agcGain = 0.5 / agcPeak;
		else	// move toward target volume
			agcGain += (0.5 / agcPeak - agcGain) * di;
	}
	else if (agcInUse) {
		// Set gain with the level control, but limit max signal
		d = agcMaxGain * agcLevel;	// target gain
		if (d > 0.5 / agcPeak)
			d = 0.5 / agcPeak;
		if (agcPeak * agcGain >= 1.0)	// clipping
			agcGain = 0.5 / agcPeak;
		else
			agcGain += (d - agcGain) * di;
	}
	else {	// For no AGC set the gain, but limit to clipping
		agcGain += (agcOffGain - agcGain) * di;
		if (agcPeak * agcGain >= 1.0)	// clipping
			agcGain = 1.0 / agcPeak;
	}
#if DEBUG
	if (printit) {
		d = CLIP32;
		printf("agcGain %12.1lf  agcMaxGain * agcLevel %.1lf  agcPeak %.6lf agcOffGain %.1lf\n",
			agcGain, agcMaxGain * agcLevel, agcPeak / 2.e9, agcOffGain);
		//printf ("Levels: %12.8lf  %12.8lf %12.8lf  %12.8lf  %12.8lf\n",
		//	levelA/d, levelB/d, levelC/d, levelD/d, levelE/d);
		levelA = levelB = levelC = levelD = levelE = 0;
	}
#endif
	if (rxMode == 5) {		// mode is FM
		if (IsSquelch(quisk_tx_tune_freq)) {
			agc_level = 0;
#if DEBUG
			if ( ! is_squelch)
				printf("close squelch\n");
#endif
			is_squelch = 1;
		}
		else {
			agc_level = agcGain * audioVolume;
#if DEBUG
			if (is_squelch)
				printf("open  squelch\n");
#endif
			is_squelch = 0;
		}
	}
	else {
		agc_level = agcGain * audioVolume;
	}
	if (keyupEnvelope < 1.0) {		// raise volume slowly after the key goes up
		di = 1. / (quisk_sound_state.playback_rate * 5e-3);		// 5 milliseconds
		for (i = 0; i < nSamples; i++) {
			keyupEnvelope += di;
			if (keyupEnvelope > 1.0)
				keyupEnvelope = 1.0;
			cSamples[i] *= keyupEnvelope * agc_level;
		}
	}
	else {
		if (quisk_record_state == RECORD && ! is_squelch)
			tmp_record(cSamples, nSamples, agcGain);		// save radio sound
		for (i = 0; i < nSamples; i++)
			cSamples[i] *= agc_level;		// apply AGC
		if (quisk_record_state == PLAYBACK)
			tmp_playback(cSamples, nSamples, audioVolume);	// replace radio sound
	}
	return nSamples;
}

static PyObject * get_state(PyObject * self, PyObject * args)
{
	int unused = 0;

	if (args && !PyArg_ParseTuple (args, ""))	// args=NULL internal call
		return NULL;
	return  Py_BuildValue("iiiiisisiiiiiiiii",
		quisk_sound_state.rate_min,
		quisk_sound_state.rate_max,
		quisk_sound_state.sample_rate,
		quisk_sound_state.chan_min,
		quisk_sound_state.chan_max,
		&quisk_sound_state.msg1,
		unused,
		&quisk_sound_state.err_msg,
		quisk_sound_state.read_error,
		quisk_sound_state.write_error,
		quisk_sound_state.underrun_error,
		quisk_sound_state.latencyCapt,
		quisk_sound_state.latencyPlay,
		quisk_sound_state.interupts,
		fft_error,
		mic_max_display,
		quisk_sound_state.data_poll_usec
		);
}

static PyObject * get_squelch(PyObject * self, PyObject * args)
{
	int freq;

	if (!PyArg_ParseTuple (args, "i", &freq))
		return NULL;
	return PyInt_FromLong(IsSquelch(freq));
}

static PyObject * get_overrange(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	return PyInt_FromLong(quisk_get_overrange());
}

static PyObject * get_filter_rate(PyObject * self, PyObject * args)
{  // return the filter sample rate as used by quisk_process_samples
	int rate;

	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	rate = 24000;
	switch(rxMode) {
	case 0:
	case 1:
		rate /= 4;	  // CW
		break;
	case 2:
	case 3:
	case 7:
	default:
		rate /= 2;	  // SSB
		break;
	case 4:
		break;		  // AM
	case 5:
		break;		  // FM
	}
	return PyInt_FromLong(rate);
}

static PyObject * get_smeter(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	return PyFloat_FromDouble(Smeter);
}

static PyObject * add_tone(PyObject * self, PyObject * args)
{  /* Add a test tone to the captured audio data */
	int freq;

	if (!PyArg_ParseTuple (args, "i", &freq))
		return NULL;
	if (freq && sample_rate)
		testtonePhase = cexp((I * 2.0 * M_PI * freq) / sample_rate);
	else
		testtonePhase = 0;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * open_key(PyObject * self, PyObject * args)
{
	const char * name;

	if (!PyArg_ParseTuple (args, "s", &name))
		return NULL;

	return PyInt_FromLong(quisk_open_key(name));
}

static PyObject * open_rx_udp(PyObject * self, PyObject * args)
{
	const char * ip;
	int port;
	char buf[128];
	struct sockaddr_in Addr;
	int recvsize;

#if DEBUG_IO
	int intbuf;
#ifdef MS_WINDOWS
	int bufsize = sizeof(int);
#else
	socklen_t bufsize = sizeof(int);
#endif
#endif

#ifdef MS_WINDOWS
	WORD wVersionRequested;
	WSADATA wsaData;
#endif

	if (!PyArg_ParseTuple (args, "si", &ip, &port))
		return NULL;
#ifdef MS_WINDOWS
	wVersionRequested = MAKEWORD(2, 2);
	if (WSAStartup(wVersionRequested, &wsaData) != 0) {
		sprintf(buf, "Failed to initialize Winsock (WSAStartup)");
		return PyString_FromString(buf);
	}
#endif
	quisk_using_udp = 1;
	rx_udp_socket = socket(PF_INET, SOCK_DGRAM, 0);
	if (rx_udp_socket != INVALID_SOCKET) {
		recvsize = 256000;
		setsockopt(rx_udp_socket, SOL_SOCKET, SO_RCVBUF, (char *)&recvsize, sizeof(recvsize));
		Addr.sin_family = AF_INET;
		Addr.sin_port = htons(port);
#ifdef MS_WINDOWS
		Addr.sin_addr.S_un.S_addr = inet_addr(ip);
#else
		inet_aton(ip, &Addr.sin_addr);
#endif
		if (connect(rx_udp_socket, (const struct sockaddr *)&Addr, sizeof(Addr)) != 0) {
			shutdown(rx_udp_socket, QUISK_SHUT_BOTH);
			close(rx_udp_socket);
			rx_udp_socket = INVALID_SOCKET;
			sprintf(buf, "Failed to connect to UDP %s port 0x%X", ip, port);
		}
		else {
			sprintf(buf, "Capture from UDP %s port 0x%X", ip, port);
#if DEBUG_IO
			if (getsockopt(rx_udp_socket, SOL_SOCKET, SO_RCVBUF, (char *)&intbuf, &bufsize) == 0)
				printf("UDP socket receive buffer size %d\n", intbuf);
			else
				printf ("Failure SO_RCVBUF\n");
#endif
		}
	}
	else {
		sprintf(buf, "Failed to open socket");
	}
	return PyString_FromString(buf);
}

static PyObject * close_rx_udp(PyObject * self, PyObject * args)
{
	short msg = 0x7373;		// shutdown

	if (!PyArg_ParseTuple (args, ""))
		return NULL;

	if (rx_udp_socket != INVALID_SOCKET) {
		shutdown(rx_udp_socket, QUISK_SHUT_RD);
		send(rx_udp_socket, (char *)&msg, 2, 0);
		send(rx_udp_socket, (char *)&msg, 2, 0);
		QuiskSleepMicrosec(3000000);
		close(rx_udp_socket);
		rx_udp_socket = INVALID_SOCKET;
	}
	rx_udp_started = 0;
	if (quisk_using_udp) {
		quisk_using_udp = 0;
#ifdef MS_WINDOWS
		WSACleanup();
#endif
	}
	Py_INCREF (Py_None);
	return Py_None;
}

int quisk_read_rx_udp(complex * samp)	// Read samples from UDP
{		// Size of complex sample array is SAMP_BUFFER_SIZE
	ssize_t bytes;
	unsigned char buf[1500];	// Maximum Ethernet is 1500 bytes.
	static unsigned char seq0;	// must be 8 bits
	int i, count, nSamples, xr, xi, index;
	unsigned char * ptxr, * ptxi;
	struct timeval tm = {0, 5000};
	fd_set fds;
	static complex dc_average = 0;		// Average DC component in samples
	static complex dc_sum = 0;
	static int dc_count = 0;
	static int dc_key_delay = 0;

	// Data from the receiver is little-endian
	if ( ! rx_udp_read_blocks) {
		// "rx_udp_read_blocks" is the number of UDP blocks to read at once
		rx_udp_read_blocks = (int)(quisk_sound_state.data_poll_usec * 1e-6 * sample_rate + 0.5);
		rx_udp_read_blocks = (rx_udp_read_blocks + (RX_UDP_SIZE / 12)) / (RX_UDP_SIZE / 6);	// 6 bytes per sample
		if (rx_udp_read_blocks < 1)
			rx_udp_read_blocks = 1;
#if DEBUG_IO
		printf("read_rx_udp:  rx_udp_read_blocks %d\n", rx_udp_read_blocks);
#endif
	}
	if ( ! rx_udp_gain_correct) {
		int dec;
		dec = (int)(rx_udp_clock / sample_rate + 0.5);
		if ((dec / 5) * 5 == dec)		// Decimation by a factor of 5
			rx_udp_gain_correct = 1.31072;
		else						// Decimation by factors of two
			rx_udp_gain_correct = 1.0;
	}
	if ( ! rx_udp_started) {	// we never received any data
		// send our return address until we receive UDP blocks
		FD_ZERO (&fds);
		FD_SET (rx_udp_socket, &fds);
		if (select (rx_udp_socket + 1, &fds, NULL, NULL, &tm) == 1) {	// see if data is available
			bytes = recv(rx_udp_socket, (char *)buf, 1500,  0);	// throw away the first block
			seq0 = buf[0] + 1;	// Next expected sequence number
			rx_udp_started = 1;
		}
		else {		// send our return address to the sample source
			buf[0] = buf[1] = 0x72;	// UDP command "register return address"
			send(rx_udp_socket, (char *)buf, 2, 0);
			return 0;
		}
	}
	nSamples = 0;
	for (count = 0; count < rx_udp_read_blocks; count++) {		// read several UDP blocks
		bytes = recv(rx_udp_socket, (char *)buf, 1500,  0);	// blocking read
		if (bytes != RX_UDP_SIZE) {		// Known size of sample block
			quisk_sound_state.read_error++;
#if DEBUG_IO
			printf("read_rx_udp: Bad block size\n");
#endif
			continue;
		}
		// buf[0] is the sequence number
		// buf[1] is the status:
		//		bit 0:  key up/down state
		//		bit 1:	set for ADC overrange (clip)
		if (buf[0] != seq0) {
#if DEBUG_IO
			printf("read_rx_udp: Bad sequence want %3d got %3d at block %d of %d\n",
					(unsigned int)seq0, (unsigned int)buf[0], count, rx_udp_read_blocks);
#endif
			quisk_sound_state.read_error++;
		}
		seq0 = buf[0] + 1;		// Next expected sequence number
		quisk_set_key_down(buf[1] & 0x01);	// bit zero is key state
		if (buf[1] & 0x02)					// bit one is ADC overrange
			quisk_sound_state.overrange++;
		index = 2;
		ptxr = (unsigned char *)&xr;
		ptxi = (unsigned char *)&xi;
		// convert 24-bit samples to 32-bit samples; int must be 32 bits.
		if (is_little_endian) {
			while (index < bytes) {
				xr = xi = 0;
				memcpy (ptxr + 1, buf + index, 3);
				index += 3;
				memcpy (ptxi + 1, buf + index, 3);
				index += 3;
				samp[nSamples++] = (xr + xi * I) * rx_udp_gain_correct;
				xr = xi = 0;
				memcpy (ptxr + 1, buf + index, 3);
				index += 3;
				memcpy (ptxi + 1, buf + index, 3);
				index += 3;
				samp[nSamples++] = (xr + xi * I) * rx_udp_gain_correct;;
	//if (nSamples == 2) printf("%12d %12d\n", xr, xi);
			}
		}
		else {		// big-endian
			while (index < bytes) {
				*(ptxr    ) = buf[index + 2];
				*(ptxr + 1) = buf[index + 1];
				*(ptxr + 2) = buf[index    ];
				*(ptxr + 3) = 0;
				index += 3;
				*(ptxi    ) = buf[index + 2];
				*(ptxi + 1) = buf[index + 1];
				*(ptxi + 2) = buf[index    ];
				*(ptxi + 3) = 0;
				index += 3;
				samp[nSamples++] = (xr + xi * I) * rx_udp_gain_correct;;
				*(ptxr    ) = buf[index + 2];
				*(ptxr + 1) = buf[index + 1];
				*(ptxr + 2) = buf[index    ];
				*(ptxr + 3) = 0;
				index += 3;
				*(ptxi    ) = buf[index + 2];
				*(ptxi + 1) = buf[index + 1];
				*(ptxi + 2) = buf[index    ];
				*(ptxi + 3) = 0;
				index += 3;
				samp[nSamples++] = (xr + xi * I) * rx_udp_gain_correct;;

			}
		}
	}
	if (quisk_is_key_down()) {
		dc_key_delay = 0;
		dc_sum = 0;
		dc_count = 0;
	}
	else if (dc_key_delay < quisk_sound_state.sample_rate) {
		dc_key_delay += nSamples;
	}
	else {
		dc_count += nSamples;
		for (i = 0; i < nSamples; i++)		// Correction for DC offset in samples
			dc_sum += samp[i];
		if (dc_count > quisk_sound_state.sample_rate * 2) {
			dc_average = dc_sum / dc_count;
			dc_sum = 0;
			dc_count = 0;
			//printf("dc average %lf   %lf %d\n", creal(dc_average), cimag(dc_average), dc_count);
			//printf("dc polar %.0lf   %d\n", cabs(dc_average),
			   		//	(int)(360.0 / 2 / M_PI * atan2(cimag(dc_average), creal(dc_average))));
		}
	}
	if (use_remove_dc)
		for (i = 0; i < nSamples; i++)	// Correction for DC offset in samples
			samp[i] -= dc_average;
	return nSamples;
}

static PyObject * open_sound(PyObject * self, PyObject * args)
{
	char * capt, * play, * mname, * mip, * mpname;

	if (!PyArg_ParseTuple (args, "ssiiissiiiidsi", &capt, &play,
				&quisk_sound_state.sample_rate,
				&quisk_sound_state.data_poll_usec,
				&quisk_sound_state.latency_millisecs,
				&mname, &mip,
				&quisk_sound_state.tx_audio_port,
				&quisk_sound_state.mic_sample_rate,
				&quisk_sound_state.mic_channel_I,
				&quisk_sound_state.mic_channel_Q,
				&quisk_sound_state.mic_out_volume,
				&mpname,
				&quisk_sound_state.mic_playback_rate
				))
		return NULL;
	if (quisk_sound_state.mic_out_volume > 0.7)	// maximum value must leave headroom for
		quisk_sound_state.mic_out_volume = 0.7;	//   the amplitude and phase adjustments
	quisk_sound_state.playback_rate = QuiskGetConfigInt("playback_rate", 48000);
	quisk_mic_preemphasis = QuiskGetConfigDouble("mic_preemphasis", 0.6);
	//if (quisk_mic_preemphasis < 0.0 || quisk_mic_preemphasis > 1.0)
	//	quisk_mic_preemphasis = 1.0;
	quisk_mic_clip = QuiskGetConfigDouble("mic_clip", 3.0);
	strncpy(quisk_sound_state.dev_capt_name, capt, QUISK_SC_SIZE);
	strncpy(quisk_sound_state.dev_play_name, play, QUISK_SC_SIZE);
	strncpy(quisk_sound_state.mic_dev_name, mname, QUISK_SC_SIZE);
	strncpy(quisk_sound_state.name_of_mic_play, mpname, QUISK_SC_SIZE);
	strncpy(quisk_sound_state.mic_ip, mip, IP_SIZE);
	fft_error = 0;
	quisk_open_sound();
	quisk_open_mic();
	sample_rate = quisk_sound_state.sample_rate;
	return get_state(NULL, NULL);
}

static PyObject * close_sound(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	quisk_close_mic();
	quisk_close_sound();
	quisk_close_key();
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * change_rate(PyObject * self, PyObject * args)	// Called from GUI thread
{	// Change to a new sample rate
	if (!PyArg_ParseTuple (args, "ii", &sample_rate, &average_count))
		return NULL;
	quisk_sound_state.sample_rate = sample_rate;
	rx_udp_read_blocks = 0;		// re-calculate
	rx_udp_gain_correct = 0;	// re-calculate
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * read_sound(PyObject * self, PyObject * args)
{
	int n;

	if (!PyArg_ParseTuple (args, ""))
		return NULL;
Py_BEGIN_ALLOW_THREADS
	n = quisk_read_sound();
Py_END_ALLOW_THREADS
	return PyInt_FromLong(n);
}

static PyObject * start_sound(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	quisk_start_sound();
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * mixer_set(PyObject * self, PyObject * args)
{
	char * card_name;
	int numid;
	double value;
	char err_msg[QUISK_SC_SIZE];

	if (!PyArg_ParseTuple (args, "sid", &card_name, &numid, &value))
		return NULL;

	quisk_mixer_set(card_name, numid, value, err_msg, QUISK_SC_SIZE);
	return PyString_FromString(err_msg);
}

static PyObject * invert_spectrum(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, "i", &quisk_invert_spectrum))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_agc(PyObject * self, PyObject * args)
{  /* Change the AGC parameters */
	if (!PyArg_ParseTuple (args, "idd", &agcInUse, &agcLevel, &agcRelease))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_filters(PyObject * self, PyObject * args)
{  // Enter the coefficients of the I and Q digital filters.  The storage for
   // filters is not malloc'd because filters may be changed while being used.
	PyObject * filterI, * filterQ;
	int i, size;
	PyObject * obj;
	char buf98[98];

	if (!PyArg_ParseTuple (args, "OOi", &filterI, &filterQ, &filter_bandwidth))
		return NULL;
	if (PySequence_Check(filterI) != 1) {
		PyErr_SetString (QuiskError, "Filter I is not a sequence");
		return NULL;
	}
	if (PySequence_Check(filterQ) != 1) {
		PyErr_SetString (QuiskError, "Filter Q is not a sequence");
		return NULL;
	}
	size = PySequence_Size(filterI);
	if (size != PySequence_Size(filterQ)) {
		PyErr_SetString (QuiskError, "The size of filters I and Q must be equal");
		return NULL;
	}
	if (size >= MAX_FILTER_SIZE) {
		snprintf(buf98, 98, "Filter size must be less than %d", MAX_FILTER_SIZE);
		PyErr_SetString (QuiskError, buf98);
		return NULL;
	}
	for (i = 0; i < size; i++) {
		obj = PySequence_GetItem(filterI, i);
		cFilterI[i] = PyFloat_AsDouble(obj);
		Py_XDECREF(obj);
		obj = PySequence_GetItem(filterQ, i);
		cFilterQ[i] = PyFloat_AsDouble(obj);
		Py_XDECREF(obj);
	}
	indexFilter = 0;
	sizeFilter = size;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_noise_blanker(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, "i", &quisk_noise_blanker))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_rx_mode(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, "i", &rxMode))
		return NULL;
	quisk_set_tx_mode();
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_tune(PyObject * self, PyObject * args)
{  /* Change the tuning frequency */
	if (!PyArg_ParseTuple (args, "ii", &rx_tune_freq, &quisk_tx_tune_freq))
		return NULL;
	if (rx_tune_freq)
		tunePhase = cexp((I * -2.0 * M_PI * rx_tune_freq) / sample_rate);
	else
		tunePhase = 0;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_sidetone(PyObject * self, PyObject * args)
{
	double delay;	// play extra silence after key-up, in milliseconds

	if (!PyArg_ParseTuple (args, "iid", &quisk_sidetoneCtrl, &rit_freq, &delay))
		return NULL;
	//printf("Sidetone control times 5 = %d\n", quisk_sidetoneCtrl * 5);
	// Simulate log taper pot
	sidetoneVolume = (exp(quisk_sidetoneCtrl * 0.006908) - 1) / 1000.0;
	sidetonePhase = cexp((I * 2.0 * M_PI * abs(rit_freq)) / quisk_sound_state.playback_rate);
	keyupDelay = (int)(quisk_sound_state.playback_rate *1e-3 * delay + 0.5);
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_squelch(PyObject * self, PyObject * args)
{  /* Change the squelch parameter */
	if (!PyArg_ParseTuple (args, "d", &squelch_level))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_volume(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, "d", &audioVolume))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_key_down(PyObject * self, PyObject * args)
{
	int down;

	if (!PyArg_ParseTuple (args, "i", &down))
		return NULL;
	quisk_set_key_down(down);
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * get_graph(PyObject * self, PyObject * args)
{
	int i, j, k, n;
	fft_data * ptFft;
	PyObject * tuple2;
	double d2, scale, zoom, deltaf;
	complex c;
	static double meter = 0;	// RMS s-meter
	static int use_fft = 1;		// Use the FFT, or return raw data

	if (!PyArg_ParseTuple (args, "idd", &k, &zoom, &deltaf))
		return NULL;
	if (k != use_fft) {		// change in data return type; re-initialize
		use_fft = k;
		count_fft = 0;
	}
	// Look for an fft ready to run.
	for (i = 0, ptFft = ptWriteFft; i < 3; i++, ptFft = ptFft->next) {
		if (ptFft->status == READY)
			break;
	}
	if (i >= 3) {	// no fft was ready
		Py_INCREF(Py_None);
		return Py_None;
	}
	if ( ! use_fft) {		// return raw data, not FFT
		use_remove_dc = 0;	// No DC removal when returning raw data
		tuple2 = PyTuple_New(data_width);
		for (i = 0; i < data_width; i++)
			PyTuple_SetItem(tuple2, i,
				PyComplex_FromDoubles(creal(ptFft->samples[i]), cimag(ptFft->samples[i])));
		ptFft->status = EMPTY;
		return tuple2;
	}
	use_remove_dc = 1;
	// Continue with FFT calculation
	for (i = 0; i < fft_size; i++)		// multiply by window
		ptFft->samples[i] *= fft_window[i];
	fftw_execute(ptFft->plan);	// Calculate FFT
	// Create RMS s-meter value at known bandwidth
	// d2 is the number of FFT bins required for the bandwidth
	// i is the starting bin number from  - sample_rate / 2 to + sample_rate / 2
	d2 = (double)filter_bandwidth * fft_size / sample_rate;
	n = (int)(floor(d2) + 0.01);		// number of whole bins to add
	switch(rxMode) {
	case 0:		// CWL:  signal centered in bandwidth
	case 1:		// CWU
	case 4:		// AM
	case 5:		// FM
	default:
		i = (int)((double)quisk_tx_tune_freq * fft_size / sample_rate - d2 / 2 + 0.5);
		break;
	case 2:		// LSB:  bandwidth is below tx frequency
		i = (int)((double)quisk_tx_tune_freq * fft_size / sample_rate - d2 + 0.5);
		break;
	case 3:		// USB:  bandwidth is above tx frequency
	case 7:
		i = (int)((double)quisk_tx_tune_freq * fft_size / sample_rate + 0.5);
		break;
	}
	if (i > - fft_size / 2 && i + n + 1 < fft_size / 2) {	// too close to edge?
		for (j = 0; j < n; i++, j++) {
			if (i < 0)
				c = ptFft->samples[fft_size + i];	// negative frequencies
			else
				c = ptFft->samples[i];				// positive frequencies
			meter += c * conj(c);		// add square of amplitude
		}
		if (i < 0)			// add fractional next bin
			c = ptFft->samples[fft_size + i];
		else
			c = ptFft->samples[i];
		meter += c * conj(c) * (d2 - n);	// fractional part of next bin
	}
	// Average the fft data into the graph in order of frequency
	k = 0;
	for (i = fft_size / 2; i < fft_size; i++)			// Negative frequencies
		fft_avg[k++] += cabs(ptFft->samples[i]);
	for (i = 0; i < fft_size / 2; i++)					// Positive frequencies
		fft_avg[k++] += cabs(ptFft->samples[i]);
	ptFft->status = EMPTY;
	if (++count_fft < average_count) {
		Py_INCREF(Py_None);	// No data yet
		return Py_None;
	}
	// We have averaged enough fft's to return the graph data.
	// Average the fft data of size fft_size into the size of data_width.
	n = (int)(zoom * (double)fft_size / data_width + 0.5);
	if (n < 1)
		n = 1;
	for (i = 0; i < data_width; i++) {	// For each graph pixel
		// find k, the starting index into the FFT data
		k = (int)(fft_size * (
			deltaf / sample_rate + zoom * ((double)i / data_width - 0.5) + 0.5) + 0.1);
		d2 = 0.0;
		for (j = 0; j < n; j++, k++)
			if (k >= 0 && k < fft_size)
				d2 += fft_avg[k];
		fft_avg[i] = d2;
	}
	scale = 1.0 / 2147483647.0 / fft_size;
	Smeter = meter * scale * scale / average_count;		// record the new s-meter value
	meter = 0;
	if (Smeter > 0)
		Smeter = 10.0 * log10(Smeter);
	else
		Smeter = -140.0;
	// This correction is for a -40 dB strong signal, and is caused by FFT leakage
	// into adjacent bins. It is the amplitude that is spread out, not the squared amplitude.
	Smeter += 4.25969;
	count_fft = 0;
	tuple2 = PyTuple_New(data_width);
	// scale = 1.0 / average_count / fft_size;	// Divide by sample count
	// scale /= pow(2.0, 31);			// Normalize to max == 1
	scale = log10(average_count) + log10(fft_size) + 31.0 * log10(2.0);
	scale *= 20.0;
	for (i = 0; i < data_width; i++) {
		d2 = 20.0 * log10(fft_avg[i]) - scale;
		if (d2 < -200)
			d2 = -200;
		current_graph[i] = d2;
		PyTuple_SetItem(tuple2, i, PyFloat_FromDouble(d2));
	}
	for (i = 0; i < fft_size; i++)
		fft_avg[i] = 0;
	return tuple2;
}

static PyObject * get_filter(PyObject * self, PyObject * args)
{
	int i, j, k, n;
	int freq, time;
	PyObject * tuple2;
	complex cx;
	double d2, scale, accI, accQ;
	double * average, * bufI, * bufQ;
	fft_data * FFT;
	fftw_complex * pt;
	double phase, delta;

	if (!PyArg_ParseTuple (args, ""))
		return NULL;

	// Create space for the fft of size data_width
	FFT = (fft_data *)malloc(sizeof(fft_data));
	FFT->status = EMPTY;
	FFT->index = 0;
	pt = FFT->samples = (fftw_complex *) fftw_malloc(sizeof(fftw_complex) * data_width);
	FFT->plan = fftw_plan_dft_1d(data_width, pt, pt, FFTW_FORWARD, FFTW_MEASURE);
	average = (double *) malloc(sizeof(double) * (data_width + sizeFilter));
	bufI = (double *) malloc(sizeof(double) * sizeFilter);
	bufQ = (double *) malloc(sizeof(double) * sizeFilter);

	for (i = 0; i < data_width + sizeFilter; i++)
		average[i] = 0.5;	// Value for freq == 0
	for (freq = 1; freq < data_width / 2.0 - 10.0; freq++) {
		delta = 2 * M_PI / data_width * freq;
		phase = 0;
		// generate some initial samples to fill the filter pipeline
		for (time = 0; time < data_width + sizeFilter; time++) {
			average[time] += cos(phase);	// current sample
			phase += delta;
			if (phase > 2 * M_PI)
				phase -= 2 * M_PI;
		}
	}
	// now filter the signal
	n = 0;
	for (time = 0; time < data_width + sizeFilter; time++) {
		d2 = average[time];
		bufI[n] = d2;
		bufQ[n] = d2;
		accI = accQ = 0;
		j = n;
		for (k = 0; k < sizeFilter; k++) {
			accI += bufI[j] * cFilterI[k];
			accQ += bufQ[j] * cFilterQ[k];
			if (++j >= sizeFilter)
				j = 0;
		}
		cx = accI + I * accQ;	// Filter output
		if (++n >= sizeFilter)
			n = 0;
		if (time >= sizeFilter)
			FFT->samples[time - sizeFilter] = cx;
	}

	for (i = 0; i < data_width; i++)	// multiply by window
		FFT->samples[i] *= fft_window[i];
	fftw_execute(FFT->plan);		// Calculate FFT
	// Normalize and convert to log10
	scale = 1. / data_width;
	for (k = 0; k < data_width; k++) {
		cx = FFT->samples[k];
		average[k] = cabs(cx) * scale;
		if (average[k] <= 1e-7)		// limit to -140 dB
			average[k] = -7;
		else
			average[k] = log10(average[k]);
	}
	// Return the graph data
	tuple2 = PyTuple_New(data_width);
	i = 0;
	// Negative frequencies:
	for (k = data_width / 2; k < data_width; k++, i++)
		PyTuple_SetItem(tuple2, i, PyFloat_FromDouble(20.0 * average[k]));

	// Positive frequencies:
	for (k = 0; k < data_width / 2; k++, i++)
		PyTuple_SetItem(tuple2, i, PyFloat_FromDouble(20.0 * average[k]));

	free(bufQ);
	free(bufI);
	free(average);
	fftw_destroy_plan(FFT->plan);
	fftw_free(FFT->samples);
	free(FFT);

	return tuple2;
}

static PyObject * Xdft(PyObject * pyseq, int inverse, int window)
{  // Native spectral order is 0 Hz to (Fs - 1).  Change this to
   // - (Fs - 1)/2 to + Fs/2.  For even Fs==32, there are 15 negative
   // frequencies, a zero, and 16 positive frequencies.  For odd Fs==31,
   // there are 15 negative and positive frequencies plus zero frequency.
   // Note that zero frequency is always index (Fs - 1) / 2.
	PyObject * obj;
	int i, j, size;
	static int fft_size = -1;			// size of fft data
	static fftw_complex * samples;		// complex data for fft
	static fftw_plan planF, planB;		// fft plan for fftW
	static double * fft_window;			// window function
	Py_complex pycx;					// Python C complex value

	if (PySequence_Check(pyseq) != 1) {
		PyErr_SetString (QuiskError, "DFT input data is not a sequence");
		return NULL;
	}
	size = PySequence_Size(pyseq);
	if (size <= 0)
		return PyTuple_New(0);
	if (size != fft_size) {		// Change in previous size; malloc new space
		if (fft_size > 0) {
			fftw_destroy_plan(planF);
			fftw_destroy_plan(planB);
			fftw_free(samples);
			free (fft_window);
		}
		fft_size = size;	// Create space for one fft
		samples = (fftw_complex *) fftw_malloc(sizeof(fftw_complex) * fft_size);
		planF = fftw_plan_dft_1d(fft_size, samples, samples, FFTW_FORWARD, FFTW_MEASURE);
		planB = fftw_plan_dft_1d(fft_size, samples, samples, FFTW_BACKWARD, FFTW_MEASURE);
		fft_window = (double *) malloc(sizeof(double) * (fft_size + 1));
		//for (i = 0, j = -fft_size / 2; i < fft_size; i++, j++) {
		for (i = 0; i <= size/2; i++) {
			if (1)	// Blackman window
				fft_window[i] = fft_window[size - i] = 0.42 + 0.50 * cos(2. * M_PI * i / size) + 
					0.08 * cos(4. * M_PI * i / size);
			else if (1)	// Hamming
				fft_window[i] = fft_window[size - i] = 0.54 + 0.46 * cos(2. * M_PI * i / size);
			else	// Hanning
				fft_window[i] = fft_window[size - i] = 0.50 + 0.50 * cos(2. * M_PI * i / size);
		}
	}
	j = (size - 1) / 2;		// zero frequency in input
	for (i = 0; i < size; i++) {
		obj = PySequence_GetItem(pyseq, j);
		if (PyComplex_Check(obj)) {
			pycx = PyComplex_AsCComplex(obj);
		}
		else if (PyFloat_Check(obj)) {
			pycx.real = PyFloat_AsDouble(obj);
			pycx.imag = 0;
		}
		else if (PyInt_Check(obj)) {
			pycx.real = PyInt_AsLong(obj);
			pycx.imag = 0;
		}
		else {
			Py_XDECREF(obj);
			PyErr_SetString (QuiskError, "DFT input data is not a complex/float/int number");
			return NULL;
		}
		samples[i] = pycx.real + I * pycx.imag;
		if (++j >= size)
			j = 0;
		Py_XDECREF(obj);
	}
	if (inverse) {		// Normalize using 1/N
		fftw_execute(planB);		// Calculate inverse FFT / N
		if (window) {
			for (i = 0; i < fft_size; i++)	// multiply by window / N
				samples[i] *= fft_window[i] / size;
		}
		else {
			for (i = 0; i < fft_size; i++)	// divide by N
				samples[i] /= size;
		}
	}
	else {
		if (window) {
			for (i = 0; i < fft_size; i++)	// multiply by window
				samples[i] *= fft_window[i];
	   }
		fftw_execute(planF);		// Calculate FFT
	}
	pyseq = PyList_New(fft_size);
	j = (size - 1) / 2;		// zero frequency in input
	for (i = 0; i < fft_size; i++) {
		pycx.real = creal(samples[i]);
		pycx.imag = cimag(samples[i]);
		PyList_SetItem(pyseq, j, PyComplex_FromCComplex(pycx));
		if (++j >= size)
			j = 0;
	}
	return pyseq;
}

static PyObject * dft(PyObject * self, PyObject * args)
{
	PyObject * tuple2;
	int window;

	window = 0;
	if (!PyArg_ParseTuple (args, "O|i", &tuple2, &window))
		return NULL;
	return Xdft(tuple2, 0, window);
}

static PyObject * is_key_down(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	return PyInt_FromLong(quisk_is_key_down());
}

static PyObject * idft(PyObject * self, PyObject * args)
{
	PyObject * tuple2;
	int window;

	window = 0;
	if (!PyArg_ParseTuple (args, "O|i", &tuple2, &window))
		return NULL;
	return Xdft(tuple2, 1, window);
}

static PyObject * record_app(PyObject * self, PyObject * args)
{  // Record the Python object for the application instance, malloc space for fft's.
	int i, j;
	fftw_complex * pt;

	if (!PyArg_ParseTuple (args, "OOiiiil", &pyApp, &quisk_pyConfig, &data_width,
		&fft_size, &average_count, &sample_rate, &quisk_mainwin_handle))
		return NULL;

	Py_INCREF(quisk_pyConfig);

	rx_udp_clock = QuiskGetConfigDouble("rx_udp_clock", 122.88e6);
	agcMaxGain = QuiskGetConfigDouble("agc_max_gain", 15000.0);
	agcOffGain = QuiskGetConfigDouble("agc_off_gain", 1400.0);
	quisk_sound_state.sample_rate = sample_rate;	// also set by open_sound()
	is_little_endian = 1;	// Test machine byte order
	if (*(char *)&is_little_endian == 1)
		is_little_endian = 1;
	else
		is_little_endian = 0;
	strncpy (quisk_sound_state.err_msg, CLOSED_TEXT, QUISK_SC_SIZE);
	count_fft = 0;
	// Create space for the fft
	if (FFT1) {
		fftw_destroy_plan(FFT1->plan);
		fftw_free(FFT1->samples);
		free(FFT1);
	}
	FFT1 = (fft_data *)malloc(sizeof(fft_data));
	FFT1->status = EMPTY;
	pt = FFT1->samples = (fftw_complex *) fftw_malloc(sizeof(fftw_complex) * fft_size);
	FFT1->plan = fftw_plan_dft_1d(fft_size, pt, pt, FFTW_FORWARD, FFTW_MEASURE);
	ptWriteFft = FFT1;
	// Create space to write samples while the first fft is in use
	if (FFT2) {
		fftw_destroy_plan(FFT2->plan);
		fftw_free(FFT2->samples);
		free(FFT2);
	}
	FFT2 = (fft_data *)malloc(sizeof(fft_data));
	FFT2->status = EMPTY;
	pt = FFT2->samples = (fftw_complex *) fftw_malloc(sizeof(fftw_complex) * fft_size);
	FFT2->plan = fftw_plan_dft_1d(fft_size, pt, pt, FFTW_FORWARD, FFTW_MEASURE);
	// Create space to write samples while the first and second fft is in use	// WB4JFI ADD
	if (FFT3) {
		fftw_destroy_plan(FFT3->plan);
		fftw_free(FFT3->samples);
		free(FFT3);
	}
	FFT3 = (fft_data *)malloc(sizeof(fft_data));
	FFT3->status = EMPTY;
	pt = FFT3->samples = (fftw_complex *) fftw_malloc(sizeof(fftw_complex) * fft_size);
	FFT3->plan = fftw_plan_dft_1d(fft_size, pt, pt, FFTW_FORWARD, FFTW_MEASURE);
	FFT1->next = FFT2;		// create pointers to the next data block
	FFT2->next = FFT3;
	FFT3->next = FFT1;
	// Create space for the fft average and window
	if (fft_avg)
		free(fft_avg);
	if (fft_window)
		free(fft_window);
	fft_avg = (double *) malloc(sizeof(double) * fft_size);
	for (i = 0; i < fft_size; i++)
		fft_avg[i] = 0;
	fft_window = (double *) malloc(sizeof(double) * fft_size);
	for (i = 0, j = -fft_size / 2; i < fft_size; i++, j++) {
		if (0)	// Hamming
			fft_window[i] = 0.54 + 0.46 * cos(2. * M_PI * j / fft_size);
		else	// Hanning
			fft_window[i] = 0.5 + 0.5 * cos(2. * M_PI * j / fft_size);
	}
	if (current_graph)
		free(current_graph);
	current_graph = (double *) malloc(sizeof(double) * data_width);
#if DEBUG_IO
	QuiskPrintTime(NULL, 0);
#endif
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * record_graph(PyObject * self, PyObject * args)
{  /* record the Python object for the application instance */
	if (!PyArg_ParseTuple (args, "iid", &graphX, &graphY, &graphScale))
		return NULL;
	graphScale *= 2;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * test_1(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * test_2(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * test_3(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, ""))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyObject * set_fdx(PyObject * self, PyObject * args)
{
	if (!PyArg_ParseTuple (args, "i", &isFDX))
		return NULL;
	Py_INCREF (Py_None);
	return Py_None;
}

static PyMethodDef QuiskMethods[] = {
	{"add_tone", add_tone, METH_VARARGS, "Add a test tone to the data."},
	{"dft", dft, METH_VARARGS, "Calculate the discrete Fourier transform."},
	{"idft", idft, METH_VARARGS, "Calculate the inverse discrete Fourier transform."},
	{"is_key_down", is_key_down, METH_VARARGS, "Check whether the key is down; return 0 or 1."},
	{"get_state", get_state, METH_VARARGS, "Return a count of read and write errors."},
	{"get_graph", get_graph, METH_VARARGS, "Return a tuple of graph data."},
	{"get_filter", get_filter, METH_VARARGS, "Return the frequency response of the receive filter."},
	{"get_filter_rate", get_filter_rate, METH_VARARGS, "Return the sample rate used for the filters."},
	{"get_tx_filter", quisk_get_tx_filter, METH_VARARGS, "Return the frequency response of the transmit filter."},
	{"get_overrange", get_overrange, METH_VARARGS, "Return the count of overrange (clip) for the ADC."},
	{"get_smeter", get_smeter, METH_VARARGS, "Return the S meter reading."},
	{"invert_spectrum", invert_spectrum, METH_VARARGS, "Invert the input RF spectrum"},
	{"record_app", record_app, METH_VARARGS, "Save the App instance."},
	{"record_graph", record_graph, METH_VARARGS, "Record graph parameters."},
	{"set_ampl_phase", quisk_set_ampl_phase, METH_VARARGS, "Set the sound card amplitude and phase corrections."},
	{"set_agc", set_agc, METH_VARARGS, "Set the AGC parameters."},
	{"set_squelch", set_squelch, METH_VARARGS, "Set the squelch parameter."},
	{"get_squelch", get_squelch, METH_VARARGS, "Get the squelch state, 0 or 1."},
	{"set_file_record", quisk_set_file_record, METH_VARARGS, "Set the state and names of the recording files."},
	{"set_filters", set_filters, METH_VARARGS, "Set the receive audio I and Q channel filters."},
	{"set_noise_blanker", set_noise_blanker, METH_VARARGS, "Set the noise blanker level."},
	{"set_record_state", set_record_state, METH_VARARGS, "Set the temp buffer record and playback state."},
	{"set_rx_mode", set_rx_mode, METH_VARARGS, "Set the receive mode: CWL, USB, AM, etc."},
	{"set_spot_level", quisk_set_spot_level, METH_VARARGS, "Set the spot mode: 0, 1, ... or -1 for no spot"},
	{"set_sidetone", set_sidetone, METH_VARARGS, "Set the sidetone volume and frequency."},
	{"set_volume", set_volume, METH_VARARGS, "Set the audio output volume."},
	{"set_tune", set_tune, METH_VARARGS, "Set the tuning frequency."},
	{"test_1", test_1, METH_VARARGS, "Test 1 function."},
	{"test_2", test_2, METH_VARARGS, "Test 2 function."},
	{"test_3", test_3, METH_VARARGS, "Test 3 function."},
	{"set_fdx", set_fdx, METH_VARARGS, "Set full duplex mode; ignore the key status."},
	{"sound_devices", quisk_sound_devices, METH_VARARGS, "Return a list of available sound device names."},
	{"sound_errors", quisk_sound_errors, METH_VARARGS, "Return a list of text strings with sound devices and error counts"},
	{"open_sound", open_sound, METH_VARARGS, "Open the the soundcard device."},
	{"close_sound", close_sound, METH_VARARGS, "Stop the soundcard and release resources."},
	{"capt_channels", quisk_capt_channels, METH_VARARGS, "Set the I and Q capture channel numbers"},
	{"play_channels", quisk_play_channels, METH_VARARGS, "Set the I and Q playback channel numbers"},
	{"micplay_channels", quisk_micplay_channels, METH_VARARGS, "Set the I and Q microphone playback channel numbers"},
	{"change_rate", change_rate, METH_VARARGS, "Change to a new sample rate"},
	{"read_sound", read_sound, METH_VARARGS, "Read from the soundcard."},
	{"start_sound", start_sound, METH_VARARGS, "Start the soundcard."},
	{"mixer_set", mixer_set, METH_VARARGS, "Set microphone mixer parameters such as volume."},
	{"open_key", open_key, METH_VARARGS, "Open access to the state of the key (CW or PTT)."},
	{"open_rx_udp", open_rx_udp, METH_VARARGS, "Open a UDP port for capture."},
	{"close_rx_udp", close_rx_udp, METH_VARARGS, "Close the UDP port used for capture."},
	{"set_key_down", set_key_down, METH_VARARGS, "Change the key up/down state for method \"\""},
	{NULL, NULL, 0, NULL}		/* Sentinel */
};

PyMODINIT_FUNC init_quisk (void)
{
	PyObject * m;
	PyObject * c_api_object;
	static void * Quisk_API[] = QUISK_API_INIT;

	m = Py_InitModule ("_quisk", QuiskMethods);
	if (m == NULL) {
		printf("Py_InitModule of _quisk failed!\n");
		return;
	}

	QuiskError = PyErr_NewException ("quisk.error", NULL, NULL);
	Py_INCREF (QuiskError);
	PyModule_AddObject (m, "error", QuiskError);

#if ( (PY_VERSION_HEX <  0x02070000) || ((PY_VERSION_HEX >= 0x03000000) && (PY_VERSION_HEX <  0x03010000)) )
// Old Python interface using CObject
       /* Create CObjects for handing _quisk symbols to C extensions in other Python modules. */
       c_api_object = PyCObject_FromVoidPtr(Quisk_API, NULL);
       if (c_api_object != NULL)
         PyModule_AddObject(m, "QUISK_C_API", c_api_object);
#else
// New Python interface using Capsule
       /* Create Capsules for handing _quisk symbols to C extensions in other Python modules. */
       c_api_object = PyCapsule_New(Quisk_API, "_quisk.QUISK_C_API", NULL);
       if (c_api_object != NULL)
         PyModule_AddObject(m, "QUISK_C_API", c_api_object);
#endif
}
