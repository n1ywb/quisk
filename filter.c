#include <Python.h>
#include <stdlib.h>
#include <math.h>
#include <complex.h>	// Use native C99 complex type for fftw3
#include "quisk.h"
#include "filter.h"
#include "filters.h"

void quisk_filt_cInit(struct quisk_cFilter * filter, double * coefs, int taps)
{	// Prepare a new filter using coefs and taps.  Samples are complex.
	filter->dCoefs = coefs;
	filter->cpxCoefs = NULL;
	filter->cSamples = (complex *)malloc(taps * sizeof(complex));
	memset(filter->cSamples, 0, taps * sizeof(complex));
	filter->ptcSamp = filter->cSamples;
	filter->nTaps = taps;
	filter->counter = 0;
	filter->cBuf = NULL;
	filter->nBuf = 0;
}

void quisk_filt_dInit(struct quisk_dFilter * filter, double * coefs, int taps)
{	// Prepare a new filter using coefs and taps.  Samples are double.
	filter->dCoefs = coefs;
	filter->cpxCoefs = NULL;
	filter->dSamples = (double *)malloc(taps * sizeof(double));
	memset(filter->dSamples, 0, taps * sizeof(double));
	filter->ptdSamp = filter->dSamples;
	filter->nTaps = taps;
	filter->counter = 0;
	filter->dBuf = NULL;
	filter->nBuf = 0;
}

void quisk_filt_tune(struct quisk_dFilter * filter, double freq, int ssb_upper)
{	// Tune a filter into an analytic I/Q filter with complex coefficients.
	// freq is the center frequency / sample rate.  Reverse coef if ssb_upper == 0.
	// This is used for both quisk_dFilter and quisk_cFilter with a cast.
	int i;
	complex coef, tune;
	double D;

	if ( ! filter->cpxCoefs)
		filter->cpxCoefs = (complex *)malloc(filter->nTaps * sizeof(complex));
	tune = I * 2.0 * M_PI * freq;
	D = (filter->nTaps - 1.0) / 2.0;
	for (i = 0; i < filter->nTaps; i++) {
		coef = 2.0 * cexp(tune * (i - D)) * filter->dCoefs[i];
		if (ssb_upper)
			filter->cpxCoefs[i] = coef;
		else
			filter->cpxCoefs[i] = cimag(coef) + I * creal(coef);
	}
}

complex quisk_dC_out(double sample, struct quisk_dFilter * filter)
{
	complex csample;
	complex * ptCoef;
	double  * ptSample;
	int k;

	// FIR bandpass filter; separate double sample into I and Q.
	// Put samples into buffer left to right.  Use samples right to left.
	ptSample = filter->ptdSamp;
	*ptSample = sample;
	ptCoef = filter->cpxCoefs;
	csample = 0;
	for (k = 0; k < filter->nTaps; k++, ptCoef++) {
		csample += *ptSample  *  *ptCoef;
		if (--ptSample < filter->dSamples)
			ptSample = filter->dSamples + filter->nTaps - 1;
	}
	if (++filter->ptdSamp >= filter->dSamples + filter->nTaps)
		filter->ptdSamp = filter->dSamples;
	return csample;
}

#if 0
complex quisk_cC_out(complex sample, struct quisk_cFilter * filter)
{
	complex csample;
	complex * ptCoef;
	complex  * ptSample;
	int k;

	// FIR bandpass filter; filter complex samples by complex coeffs.
	// Put samples into buffer left to right.  Use samples right to left.
	ptSample = filter->ptcSamp;
	*ptSample = sample;
	ptCoef = filter->cpxCoefs;
	csample = 0;
	for (k = 0; k < filter->nTaps; k++, ptCoef++) {
		csample += *ptSample  *  *ptCoef;
		if (--ptSample < filter->cSamples)
			ptSample = filter->cSamples + filter->nTaps - 1;
	}
	if (++filter->ptcSamp >= filter->cSamples + filter->nTaps)
		filter->ptcSamp = filter->cSamples;
	return csample;
}
#endif

int quisk_cInterpolate(complex * cSamples, int count, struct quisk_cFilter * filter, int interp)
{	// This uses the double coefficients of filter (not the complex).  Samples are complex.
	int i, j, k, nOut;
	double * ptCoef;
	complex * ptSample;
	complex csample;

	if (count > filter->nBuf) {	// increase size of sample buffer
		filter->nBuf = count * 2;
		if (filter->cBuf)
			free(filter->cBuf);
		filter->cBuf = (complex *)malloc(filter->nBuf * sizeof(complex));
	}
	memcpy(filter->cBuf, cSamples, count * sizeof(complex));
	nOut = 0;
	for (i = 0; i < count; i++) {
		// Put samples into buffer left to right.  Use samples right to left.
		*filter->ptcSamp = filter->cBuf[i];
		for (j = 0; j < interp; j++) {
			ptSample = filter->ptcSamp;
			ptCoef = filter->dCoefs + j;
			csample = 0;
			for (k = 0; k < filter->nTaps / interp; k++, ptCoef += interp) {
				csample += *ptSample  *  *ptCoef;
				if (--ptSample < filter->cSamples)
					ptSample = filter->cSamples + filter->nTaps - 1;
			}
			cSamples[nOut++] = csample * interp;
		}
		if (++filter->ptcSamp >= filter->cSamples + filter->nTaps)
			filter->ptcSamp = filter->cSamples;
	}
	return nOut;
}

int quisk_dInterpolate(double * dSamples, int count, struct quisk_dFilter * filter, int interp)
{	// This uses the double coefficients of filter (not the complex).  Samples are double.
	int i, j, k, nOut;
	double * ptCoef;
	double * ptSample;
	double dsample;

	if (count > filter->nBuf) {	// increase size of sample buffer
		filter->nBuf = count * 2;
		if (filter->dBuf)
			free(filter->dBuf);
		filter->dBuf = (double *)malloc(filter->nBuf * sizeof(double));
	}
	memcpy(filter->dBuf, dSamples, count * sizeof(double));
	nOut = 0;
	for (i = 0; i < count; i++) {
		// Put samples into buffer left to right.  Use samples right to left.
		*filter->ptdSamp = filter->dBuf[i];
		for (j = 0; j < interp; j++) {
			ptSample = filter->ptdSamp;
			ptCoef = filter->dCoefs + j;
			dsample = 0;
			for (k = 0; k < filter->nTaps / interp; k++, ptCoef += interp) {
				dsample += *ptSample  *  *ptCoef;
				if (--ptSample < filter->dSamples)
					ptSample = filter->dSamples + filter->nTaps - 1;
			}
			dSamples[nOut++] = dsample * interp;
		}
		if (++filter->ptdSamp >= filter->dSamples + filter->nTaps)
			filter->ptdSamp = filter->dSamples;
	}
	return nOut;
}

int quisk_cDecimate(complex * cSamples, int count, struct quisk_cFilter * filter, int decim)
{	// This uses the double coefficients of filter (not the complex).
	int i, k, nOut;
	complex * ptSample;
	double * ptCoef;
	complex csample;

	nOut = 0;
	for (i = 0; i < count; i++) {
		*filter->ptcSamp = cSamples[i];
		if (++filter->counter >= decim) {
			filter->counter = 0;		// output a sample
			csample = 0;
			ptSample = filter->ptcSamp;
			ptCoef = filter->dCoefs;
			for (k = 0; k < filter->nTaps; k++, ptCoef++) {
				csample += *ptSample  *  *ptCoef;
				if (--ptSample < filter->cSamples)
					ptSample = filter->cSamples + filter->nTaps - 1;
			}
			cSamples[nOut++] = csample;
		}
		if (++filter->ptcSamp >= filter->cSamples + filter->nTaps)
			filter->ptcSamp = filter->cSamples;
	}
	return nOut;
}

int quisk_dDecimate(double * dSamples, int count, struct quisk_dFilter * filter, int decim)
{	// This uses the double coefficients of filter (not the complex).
	int i, k, nOut;
	double * ptSample;
	double * ptCoef;
	double dsample;

	nOut = 0;
	for (i = 0; i < count; i++) {
		*filter->ptdSamp = dSamples[i];
		if (++filter->counter >= decim) {
			filter->counter = 0;		// output a sample
			dsample = 0;
			ptSample = filter->ptdSamp;
			ptCoef = filter->dCoefs;
			for (k = 0; k < filter->nTaps; k++, ptCoef++) {
				dsample += *ptSample  *  *ptCoef;
				if (--ptSample < filter->dSamples)
					ptSample = filter->dSamples + filter->nTaps - 1;
			}
			dSamples[nOut++] = dsample;
		}
		if (++filter->ptdSamp >= filter->dSamples + filter->nTaps)
			filter->ptdSamp = filter->dSamples;
	}
	return nOut;
}

int quisk_dFilter(double * dSamples, int count, struct quisk_dFilter * filter)
{	// Filter double samples.
	int i, k, nOut;
	double * ptSample;
	double * ptCoef;
	double dsample;

	nOut = 0;
	for (i = 0; i < count; i++) {
		*filter->ptdSamp = dSamples[i];
		dsample = 0;
		ptSample = filter->ptdSamp;
		ptCoef = filter->dCoefs;
		for (k = 0; k < filter->nTaps; k++, ptCoef++) {
			dsample += *ptSample  *  *ptCoef;
			if (--ptSample < filter->dSamples)
				ptSample = filter->dSamples + filter->nTaps - 1;
		}
		dSamples[nOut++] = dsample;
		if (++filter->ptdSamp >= filter->dSamples + filter->nTaps)
			filter->ptdSamp = filter->dSamples;
	}
	return nOut;
}

int quisk_cDecim2HB45(complex * cSamples, int count, struct quisk_cHB45Filter * filter)
{	// This uses the double coefficients of filter (not the complex).
// Half band filter, sample rate 96 Hz, pass 16, center 24, stop 32, good BW 2/3, 45 taps.
	int i, nOut;
	complex * samples, * center;
	static double coef[12] = { 0.000018566625444266, -0.000118469698701817, 0.000457318798253456,
	-0.001347840471412094, 0.003321838571445455, -0.007198422696929033, 0.014211106939802483,
	-0.026424776824073383, 0.048414810444971007, -0.096214669073304823, 0.314881034738348550,
	0.500000000000000000 }; // Rate 96, cutoff 16-24-32, atten 120 dB.  Coef[0] and [44] are zero.

	nOut = 0;
	samples = filter->samples;
	center = filter->center;
	for (i = 0; i < count; i++) {
		if (filter->toggle == 0){
			filter->toggle = 1;
			memmove(center + 1, center, sizeof(complex) * 10);
			center[0] = cSamples[i];
		}
		else {
			filter->toggle = 0;
			memmove(samples + 1, samples, sizeof(complex) * 21);
			samples[0] = cSamples[i];
			// output a sample
			cSamples[nOut++] =
			(samples[ 0] + samples[21]) * coef[0] +
			(samples[ 1] + samples[20]) * coef[1] +
			(samples[ 2] + samples[19]) * coef[2] +
			(samples[ 3] + samples[18]) * coef[3] +
			(samples[ 4] + samples[17]) * coef[4] +
			(samples[ 5] + samples[16]) * coef[5] +
			(samples[ 6] + samples[15]) * coef[6] +
			(samples[ 7] + samples[14]) * coef[7] +
			(samples[ 8] + samples[13]) * coef[8] +
			(samples[ 9] + samples[12]) * coef[9] +
			(samples[10] + samples[11]) * coef[10] +
			center[10] * coef[11];
		}
	}
	return nOut;
}


int quisk_dInterp2HB45(double * dsamples, int count, struct quisk_dHB45Filter * filter)
{  // Half-Band interpolation by 2
	int i, k, nOut, nCoef, nSamp;
	double out;
	double * samples;
	static double coef[12] = { 0.000018566625444266, -0.000118469698701817, 0.000457318798253456,
	-0.001347840471412094, 0.003321838571445455, -0.007198422696929033, 0.014211106939802483,
	-0.026424776824073383, 0.048414810444971007, -0.096214669073304823, 0.314881034738348550,
	0.500000000000000000 }; // Rate 96, cutoff 16-24-32, atten 120 dB.  Coef[0] and [44] are zero.

	if (count > filter->nBuf) {	// increase size of sample buffer
		filter->nBuf = count * 2;
		if (filter->dBuf)
			free(filter->dBuf);
		filter->dBuf = (double *)malloc(filter->nBuf * sizeof(double));
	}
	nCoef = 12;
	nSamp = (nCoef - 1) * 2;
	memcpy(filter->dBuf, dsamples, count * sizeof(double));
	samples = filter->samples;
	nOut = 0;
	for (i = 0; i < count; i++) {
		memmove(samples + 1, samples, (nSamp - 1) * sizeof(double));
		samples[0] = filter->dBuf[i];
		dsamples[nOut++] = samples[nCoef - 1] * coef[nCoef - 1] * 2;
		out = 0;
		for (k = 0; k < nSamp / 2; k++)
			out += (samples[k] + samples[nSamp - 1 - k]) * coef[k];
		dsamples[nOut++] = out * 2;
	}
	return nOut;
}

