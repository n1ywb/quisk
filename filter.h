struct quisk_cFilter {
	double  * dCoefs;	// filter coefficients
	complex * cpxCoefs;	// make the complex coefficients from dCoefs
	int nBuf;		// dimension of cBuf
	int nTaps;		// dimension of dSamples, cSamples, dCoefs and cpxCoefs
	int counter;		// used to count samples for decimation
	complex * cSamples;	// storage for old samples
	complex * ptcSamp;	// next available position in cSamples
	complex * cBuf;		// auxillary buffer for interpolation
} ;

struct quisk_dFilter {
	double  * dCoefs;	// filter coefficients
	complex * cpxCoefs;	// make the complex coefficients from dCoefs
	int nBuf;		// dimension of dBuf
	int nTaps;		// dimension of dSamples, cSamples, dCoefs and cpxCoefs
	int counter;		// used to count samples for decimation
	double  * dSamples;	// storage for old samples
	double  * ptdSamp;	// next available position in dSamples
	double  * dBuf;		// auxillary buffer for interpolation
} ;

struct quisk_cHB45Filter {   // Complex half band decimate by 2 filter with 45 coefficients
	complex * cBuf;		// auxillary buffer for interpolation
	int nBuf;		// dimension of cBuf
	int toggle;
	complex samples[22];
	complex center[11];
} ;

struct quisk_dHB45Filter {   // Real half band decimate by 2 filter with 45 coefficients
	double * dBuf;		// auxillary buffer for interpolation
	int nBuf;		// dimension of dBuf
	int toggle;
	double samples[22];
	double center[11];
} ;

void quisk_filt_cInit(struct quisk_cFilter *, double *, int);
void quisk_filt_dInit(struct quisk_dFilter *, double *, int);
void quisk_filt_tune(struct quisk_dFilter *, double, int);
complex quisk_dC_out(double, struct quisk_dFilter *);
int quisk_cInterpolate(complex *, int, struct quisk_cFilter *, int);
int quisk_dInterpolate(double *, int, struct quisk_dFilter *, int);
int quisk_cDecimate(complex *, int, struct quisk_cFilter *, int);
int quisk_dDecimate(double *, int, struct quisk_dFilter *, int);
int quisk_cDecim2HB45(complex *, int, struct quisk_cHB45Filter *);
int quisk_dInterp2HB45(double *, int, struct quisk_dHB45Filter *);
int quisk_dFilter(double *, int, struct quisk_dFilter *);

extern double quiskMicFilt48Coefs[325];
extern double quiskMicFilt8Coefs[93];
extern double quiskLpFilt48Coefs[144];
extern double quiskFilt12_19Coefs[64];
extern double quiskFilt185D3Coefs[88];
extern double quiskFilt185D7Coefs[325];
extern double quiskFilt133D5Coefs[235];
extern double quiskFilt111D4Coefs[196];
extern double quiskFilt53D2Coefs[93];
extern double quiskFilt240D5Coefs[114];
extern double quiskFilt48dec24Coefs[98];
extern double quiskAudio24p6Coefs[36];
extern double quiskAudio48p6Coefs[71];
extern double quiskAudio96Coefs[11];
extern double quiskAudio24p4Coefs[47];
extern double quiskAudioFmHpCoefs[309];
extern double quiskAudio24p3Coefs[93];
