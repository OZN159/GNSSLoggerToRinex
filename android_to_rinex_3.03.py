#!/usr/bin/env python
"""
Tool to convert from logfile of GPS-measurements to RINEX format
"""
import argparse
import datetime
import math
import sys

# Define constants
SPEED_OF_LIGHT = 299792458.0 # [m/s]
GPS_WEEKSECS = 604800 # Number of seconds in a week
NS_TO_S = 1.0e-9
S_TO_NS = 1.0e9
NS_TO_M = (NS_TO_S * SPEED_OF_LIGHT)  # Constant to transform from nanoseconds to meters

#GPS
GPS_L1_FREQ = 1575.42e6
GPS_L1_WAVELENGTH = (SPEED_OF_LIGHT / GPS_L1_FREQ)
GPS_L2_FREQ = 1227.6e6
GPS_L2_WAVELENGTH = (SPEED_OF_LIGHT / GPS_L2_FREQ)
GPS_L5_FREQ = 1176.45e6
GPS_L5_WAVELENGTH = (SPEED_OF_LIGHT / GPS_L5_FREQ)

#BDS
BDS_L1_FREQ = 1561.098e6
BDS_L1_WAVELENGTH = (SPEED_OF_LIGHT / BDS_L1_FREQ)
BDS_L2_FREQ = 1207.14e6
BDS_L2_WAVELENGTH = (SPEED_OF_LIGHT / BDS_L2_FREQ)
BDS_L3_FREQ = 1268.52e6
BDS_L3_WAVELENGTH = (SPEED_OF_LIGHT / BDS_L3_FREQ)

#GAL
GAL_E1_FREQ = 1575.42e6
GAL_E1_WAVELENGTH = (SPEED_OF_LIGHT / GAL_E1_FREQ)
GAL_E5A_FREQ = 1176.45e6
GAL_E5A_WAVELENGTH = (SPEED_OF_LIGHT / GAL_E5A_FREQ)
GAL_E5B_FREQ = 1207.14e6
GAL_E5B_WAVELENGTH = (SPEED_OF_LIGHT / GAL_E5B_FREQ)
GAL_E6_FREQ = 1278.75e6
GAL_E6_WAVELENGTH = (SPEED_OF_LIGHT / GAL_E6_FREQ)

#GLNOSS
GLO_L1_FREQ_BASE = 1602000000.0
GLO_L2_FREQ_BASE = 1246000000.0
GLO_L1_FREQ_STEP = 562500.0
GLO_L2_FREQ_STEP = 437500.0 

#QZSS
QZS_L1_FREQ = 1575.42e6
QZS_L1_WAVELENGTH = (SPEED_OF_LIGHT / QZS_L1_FREQ)
QZS_L2_FREQ = 1227.6e6
QZS_L2_WAVELENGTH = (SPEED_OF_LIGHT / QZS_L2_FREQ)

#Constant
NUM_NANOSEC_WEEK = 604800e9
NUM_NANOSEC_DAY = 86400e9
NUM_NANOSEC_100MILL = 1e8
MAX_VALUE = 8388608

# Origin of the GPS time scale
GPSTIME = datetime.datetime(1980, 1, 6)

# Flags to check wether the measurement is correct or not
# https://developer.android.com/reference/android/location/GnssMeasurement.html#getState()
STATE_CODE_LOCK = int(0x00000001)
STATE_TOW_DECODED = int(0x00000008)

# Constellation types
CONSTELLATION_GPS = 1
CONSTELLATION_SBAS = 2
CONSTELLATION_GLONASS = 3
CONSTELLATION_QZSS = 4
CONSTELLATION_BEIDOU = 5
CONSTELLATION_GALILEO = 6
CONSTELLATION_UNKNOWN = 0

#Accumulated Delta Range State
ADR_STATE_UNKNOWN = int(0x00000000)
ADR_STATE_VALID = int(0x00000001)
ADR_STATE_RESET = int(0x00000002)
ADR_STATE_HALF_CYCLE_RESOLVED = int(0x00000008)
ADR_STATE_HALF_CYCLE_REPORTED = int(0x00000010)
ADR_STATE_CYCLE_SLIP = int(0x00000004)

GLN_LIST = (1, -4, 5, 6, 1, -4, 5, 6, -2, -7, 0, -1, -2, -7, 0, -1, -6, -3, 3, 2, 4, -3, 3, 2)


def get_glo_L1(chel):
    return SPEED_OF_LIGHT / (GLO_L1_FREQ_BASE + chel * GLO_L1_FREQ_STEP)

def get_glo_L2(chel):
    return SPEED_OF_LIGHT / (GLO_L2_FREQ_BASE + chel * GLO_L2_FREQ_STEP)


def get_correction_adr(psr, adr_cycles, wave_length):
    adr_rolls = (psr / wave_length + adr_cycles) / MAX_VALUE
    if adr_rolls <= 0:
        adr_rolls = adr_rolls - 0.5
    else:
        adr_rolls = adr_rolls + 0.5

    adr_cycles = -(adr_cycles - (MAX_VALUE * adr_rolls))
    return adr_cycles


def get_raw_field_descr_from_header(file_handler):
    """
    Get the raw field descriptors of the GNSS Logger log. These field descriptors
    will be later used to identify the data.

    This method advances the file pointer past the line where the raw fields
    are described
    """

    for line in file_handler:

        # Check if the line is the line containing the field descriptors of the
        # "Raw" lines
        if line.startswith("# Raw"):

            return [f.strip() for f in line[2:].strip().split(',')[1:]]


def check_state(state):
    """
    Checks if measurement is valid or not based on the Sync bits
    """

    if (state & STATE_CODE_LOCK) == 0:
        raise Exception("State [ 0x{0:2x} {0:8b} ]??has STATE_CODE_LOCK [ 0x{1:2x} {1:8b} ]??not valid".format(state, STATE_CODE_LOCK))

    if (state & STATE_TOW_DECODED) == 0:
        raise Exception("State [ 0x{0:2x} {0:8b} ]??has STATE_TOW_DECODED [ 0x{1:2x} {1:8b} ]??not valid".format(state, STATE_TOW_DECODED))

    return True


def check_adr_state(state):
    """
    Checks if measurement is valid or not based on the Sync bits
    """

    if (state & ADR_STATE_VALID) == 0:
        raise ValueError("ADR State [ 0x{0:2x} {0:8b} ] has ADR_STATE_VALID [ 0x{1:2x} {1:8b} ] not valid".format(state, ADR_STATE_VALID))
    return True


def check_rinex_field(name, value, size):
    """
    Checks if the field is of proper length and if not, it issues a 
    warning message and returns a sanitized (cropeed) version of the 
    field
    """

    if value is None:
        return "UNKN"

    if (len(value) > size):
        sys.stderr.write("The '{0}' field [ {1} ] is too long [ {2} ]. Cropping to {3} characters\n".format(name, value, len(value), size))
        
        return value[0:size]

    return value


def rinex_header(runby=None, marker=None, observer=None, agency=None,
                 receiver=None, rxtype=None, version='Android OS >7.0',
                 antenna=None, anttype='internal',
                 approx_position=[0,0,0], antenna_hen=[0.0, 0.0, 0.0]):
    """
    Print RINEX header as a string

    The fields are the ones specified in the RINEX format definition, that can
    be found at:
    https://igscb.jpl.nasa.gov/igscb/data/format/rinex211.txt
    """


    VERSION = 3.03
    TYPE = 'OBSERVATION DATA'
    SATSYS = 'M: Mixed'

    # Version line
    h = "{0:9.2f}           {1:<20}{2:<20}RINEX VERSION / TYPE\n".format(VERSION, TYPE, SATSYS)
   
    # Pgm line
    PGM = 'ANDROID_RINEX'
    datestr = datetime.datetime.now().strftime("%Y%m%d %H%M%S UTC")

    runby = check_rinex_field('RUNBY', runby, 20)
    h += "{0:<20}{1:<20}{2:<20}PGM / RUN BY / DATE\n".format(PGM, runby, datestr)

    # Additional comment line for the program
    h += "{0:<60}COMMENT\n".format("Generated by Hi-target android_rinex program")
    h += "{0:<60}COMMENT\n".format("Contact us at Nander@hitargetgroup.com.cn")

    # Marker name
    marker = check_rinex_field('MARKER NAME', marker, 60)
    h += "{0:<60}MARKER NAME\n".format(marker if marker is not None else "UNKN")
    
    # Marker type
    marker = check_rinex_field('MARKER TYPE', marker, 60)
    h += "{0:<60}MARKER TYPE\n".format(marker if marker is not None else "UNKN")

    # Observer and agency
    observer = check_rinex_field('OBSERVER', observer, 20)
    agency = check_rinex_field('AGENCY', agency, 40)
    h += "{0:<20}{1:<40}OBSERVER / AGENCY\n".format(observer, agency)
   
    # Receiver line
    receiver = check_rinex_field('RECEIVER NUMBER', receiver, 20)
    rxtype = check_rinex_field('RECEIVER TYPE', rxtype, 20)
    version = check_rinex_field('RECEIVER VERSION', version, 20)
    h += "{0:<20}{1:<20}{2:<20}REC # / TYPE / VERS\n".format(receiver, rxtype, version)
    
    # Antenna type
    antenna = check_rinex_field('ANTENNA NUMBER', antenna, 20)
    anttype = check_rinex_field('ANTENNA TYPE', anttype, 40)
    h += "{0:<20}{1:<40}ANT # / TYPE\n".format(antenna, anttype)
    
    # Approximate position
    h += "{0:14.4f}{1:14.4f}{2:14.4f}                  APPROX POSITION XYZ\n".format(*(approx_position))

    # Antenna offset
    h += "{0:14.4f}{1:14.4f}{2:14.4f}                  ANTENNA: DELTA H/E/N\n".format(*(antenna_hen))

    # Observables 
    h += '''G    8 C1C L1C D1C S1C C5Q L5Q D5Q S5Q                      SYS / # / OBS TYPES\n\
R    4 C1C L1C D1C S1C                                      SYS / # / OBS TYPES\n\
E   12 C1C L1C D1C S1C C5I L5I D5I S5I C7I L7I D7I S7I      SYS / # / OBS TYPES\n\
C    4 C2I L2I D2I S2I                                      SYS / # / OBS TYPES\n\
J    8 C1C L1C D1C S1C C5Q L5Q D5Q S5Q                      SYS / # / OBS TYPES"\n'''

    return h


def end_header(first_epoch):

    h  = first_epoch.strftime("  %Y    %m    %d    %H    %M    %S.%f                 TIME OF FIRST OBS\n")
    h += ''' 24 R01  1 R02 -4 R03  5 R04  6 R05  1 R06 -4 R07  5 R08  6 GLONASS SLOT / FRQ #\n\
    R09 -2 R10 -5 R11  0 R12 -1 R13 -2 R14 -7 R15  0 R16 -1 GLONASS SLOT / FRQ #\n\
    R17  4 R18 -3 R19  3 R20  2 R21  4 R22 -3 R23  3 R24  2 GLONASS SLOT / FRQ #\n\
G L1C                                                       SYS / PHASE SHIFT\n\
G L5Q -0.25000                                              SYS / PHASE SHIFT\n\
R L1C                                                       SYS / PHASE SHIFT\n\
E L1B                                                       SYS / PHASE SHIFT\n\
E L1C +0.50000                                              SYS / PHASE SHIFT\n\
E L5Q -0.25000                                              SYS / PHASE SHIFT\n\
C L2I                                                       SYS / PHASE SHIFT\n\
J L1C                                                       SYS / PHASE SHIFT\n\
J L5Q -0.25000                                              SYS / PHASE SHIFT\n\
 C1C    0.000 C1P    0.000 C2C    0.000 C2P    0.000        GLONASS COD/PHS/BIS\n'''
    h += "{0:<60}END OF HEADER\n".format(" ")

    return h



def gpstime_to_epoch(week, sow):
    """
    Converts from full cycle GPS time (week and seconds) to date and time

    """

    epoch = GPSTIME + datetime.timedelta(weeks=week, seconds=sow)

    return epoch




class RinexBatch:
    """
    Class that stores a Batch of measurements corresponding to the same epoch
    """

    def __init__(self, epoch):
        """
        Sets (or resets) the class
        """

        self.__clear()

        self.epoch = epoch

    def add(self, codeType, svid, c1, s1, l1, d1):
        """
        Add measurement to a batch

        - C/A needs to be specified in meters
        - SNR must be specified as dB-Hz
        - L1 phase, if provided, needs to be specified in cycles
        - D1 doppler, expressed in Hz and positive if satellite is approaching,
          which is opposite of Android API.
        """
        i = 0;

        for id in self.svids:
            if svid == id:
                if codeType == "L1" or codeType == "E1" or codeType == "B1":
                    self.c1[i] = c1
                    self.s1[i] = s1
                    self.l1[i] = l1
                    self.d1[i] = d1
                    return
                else:
                    self.c2[i] = c1
                    self.s2[i] = s1
                    self.l2[i] = l1
                    self.d2[i] = d1
                    return
            i = i + 1

        if codeType == "L1" or codeType == "E1" or codeType == "B1":   
            self.svids.append(svid)
            self.c1.append(c1)
            self.s1.append(s1)
            self.l1.append(l1)
            self.d1.append(d1)
            self.c2.append("")
            self.s2.append("")
            self.l2.append("")
            self.d2.append("")
        else:
            self.svids.append(svid)
            self.c1.append("")
            self.s1.append("")
            self.l1.append("")
            self.d1.append("")
            self.c2.append(c1)
            self.s2.append(s1)
            self.l2.append(l1)
            self.d2.append(d1)

        return


    def print(self):
        """
        Prints batch. 

        It generates a string with the batch as a RINEX epoch.

        After printing the data, the method clears the data

        There have been some cases where the epoch in the smartphones are 
        repeated, therefore, this routine checks if there are repeated entries.
        In this case it skips all the epoch altogether.
        """

        # Check for repeated emtries. In this case skip
        for sat in self.svids:
            if self.svids.count(sat) > 1:

                sys.stderr.write(self.epoch.strftime("Detected repeated entries in epoch [ %Y-%m-%d %H:%M:%S.%f ]. Skipping\n"))
                return ""

        b = self.epoch.strftime("> %Y %m %d %H %M %S.%f   0" + "{0:3d}".format(len(self.svids)))
        data = ""

        for i in range(len(self.svids)):
            if 'G' in self.svids[i]:
                data += "{0:5}{1:>12}  {2:>14}  {3:>14}  {4:>14}  {5:>14}  {6:>14}  {7:>14}  {8:>14}\n".format(self.svids[i], self.c1[i], self.l1[i], self.d1[i], self.s1[i], self.c2[i], self.l2[i], self.d2[i], self.s2[i])
        for i in range(len(self.svids)):
            if 'C' in self.svids[i]:
                data += "{0:5}{1:>12}  {2:>14}  {3:>14}  {4:>14}  {5:>14}  {6:>14}  {7:>14}  {8:>14}\n".format(self.svids[i], self.c1[i], self.l1[i], self.d1[i], self.s1[i], self.c2[i], self.l2[i], self.d2[i], self.s2[i])
        for i in range(len(self.svids)):
            if 'E' in self.svids[i]:
                data += "{0:5}{1:>12}  {2:>14}  {3:>14}  {4:>14}  {5:>14}  {6:>14}  {7:>14}  {8:>14}\n".format(self.svids[i], self.c1[i], self.l1[i], self.d1[i], self.s1[i], self.c2[i], self.l2[i], self.d2[i], self.s2[i])
        for i in range(len(self.svids)):
            if 'R' in self.svids[i]:
                data += "{0:5}{1:>12}  {2:>14}  {3:>14}  {4:>14}  {5:>14}  {6:>14}  {7:>14}  {8:>14}\n".format(self.svids[i], self.c1[i], self.l1[i], self.d1[i], self.s1[i], self.c2[i], self.l2[i], self.d2[i], self.s2[i])
        for i in range(len(self.svids)):
            if 'J' in self.svids[i]:
                data += "{0:5}{1:>12}  {2:>14}  {3:>14}  {4:>14}  {5:>14}  {6:>14}  {7:>14}  {8:>14}\n".format(self.svids[i], self.c1[i], self.l1[i], self.d1[i], self.s1[i], self.c2[i], self.l2[i], self.d2[i], self.s2[i])

        return b + "\n" + data 


    def __clear(self):
        """
        Clear the data stored in the object
        """


        self.epoch = None

        # List of satellite PRN numbers (identifiers)
        self.svids = []
        # List of code ranges
        self.c1 = []
        self.c2 = []
        # List of carrier phases
        self.l1 = []
        self.l2 = []
        # List of C/N0
        self.s1 = []
        self.s2 = []
        # List of C/N0
        self.d1 = []
        self.d2 = []


if __name__ == "__main__":

    # Parse command line
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('input_log', metavar='<input log file>', type=str,
                        help="Log file as recorded by the Google's Android app GnssLogger")
    parser.add_argument('--output', '-o', metavar='<output rinex file>', type=str, default=None,
                        help="Output RINEX file. If not set (default), RINEX will be written to the standard output")
    parser.add_argument('--marker-name', '-m', metavar='<marker name>', type=str, default="UNKN",
                        help="Specify the marker name (station id)")
    parser.add_argument('--observer', '-n', metavar='<observer name>', type=str, default="UNKN",
                        help="Specify the observer name or e-mail")
    parser.add_argument('--agency', '-a', metavar='<agency name>', type=str, default="UNKN",
                        help="Specify the agency name")
    parser.add_argument('--receiver-number',  metavar='<str>', type=str, default="UNKN",
                        help="Specify the receiver number")
    parser.add_argument('--receiver-type',  metavar='<str>', type=str, default="UNKN",
                        help="Specify the receiver type")
    parser.add_argument('--receiver-version',  metavar='<str>', type=str, default="AndroidOS >7.0",
                        help="Specify the receiver version")
    parser.add_argument('--antenna-number',  metavar='<str>', type=str, default="UNKN",
                        help="Specify the antenna number")
    parser.add_argument('--skip-edit', dest='skip_edit', action='store_true',
                        help="Skip pseudorange data edit that checks that the range is within bounds")
    parser.add_argument('--antenna-type',  metavar='<str>', type=str, default="internal",
                        help="Specify the receiver type")
    parser.add_argument('--fix-bias', '-b', dest='fix_bias', action='store_true',
                        help="FIx and hold FullBiasNanos. Use this flag to take "
                        "the first FullBiasNanos and fix it during all data "
                        "take. This will avoid pseudorange jumps that would "
                        "appear if this option is not used. Note that in some "
                        "cases, it has detected that, while the pseudorange does "
                        "have these jumps, the carrier phase does not have it.")
    parser.add_argument('--integerize', '-i', dest='integerize', action='store_true',
                        default=False,
                        help="Integerize epochs to nearest integer second. If "+
                             "selected, the range rate will be used to refer "+
                             "the range to the integer epoch as well and thus, "+
                             "maintain the consistency between time stamp and "+
                             "measurement. By default, this option is deactivated")

    args = parser.parse_args()

    # Open input log for reading 
    fh = open(args.input_log, "r")

    # Handler for the output RINEX
    out = open(args.output, "w") if args.output is not None else sys.stdout

    # Get the description of the fields at the Raw 
    raw_field_descr = get_raw_field_descr_from_header(fh)

    out.write(rinex_header(marker=args.marker_name,
                           observer=args.observer,
                           agency=args.agency,
                           receiver=args.receiver_number,
                           rxtype=args.receiver_type,
                           version=args.receiver_version,
                           antenna=args.antenna_number,
                           anttype=args.antenna_type))

    first_epoch = None

    # Rinex Batch
    rinex_batch = None

    # Full bias nanos to be used in the process
    fullbiasnanos = None

    # Loop over the file looking for Raw lines
    for line in fh:

        if not line.startswith("Raw,"):
            continue

        fields = [float(v) if len(v) > 0 else None for v in line.strip().split(',')[1:]]

        # Check that the expected number of fields is the same as the one
        # indicated in the header
        if len(fields) != len(raw_field_descr):
            sys.stderr.write("Incorrect number of fields in 'Raw' line: " +
                             "expected [ {0}??], ".format(len(raw_field_descr)) +
                             "got [ {0} ]. Skipping line [ {1} ]\n".format(len(fields), line))

            continue

        # Build a map with the fields so that they can be more accessible
        # and easier to understand later in the process
        values = dict(zip(raw_field_descr, fields))

        # Skip this measurement if no synched
        try:
            check_state(int(values['State']))
        except Exception as e:
            sys.stderr.write("Invalid state [ {0} ] for measurement: [ {1} ]\n".format(e, line))


        # Set the fullbiasnanos if not set or if we need to update the full bias
        # nanos at each epoch 
        if fullbiasnanos is None or not args.fix_bias :
            fullbiasnanos = float(values['FullBiasNanos'])

        # Compute the GPS week number as well as the time within the week of
        # the reception time (i.e. clock epoch)
        gpsweek = math.floor(-fullbiasnanos * NS_TO_S / GPS_WEEKSECS)
        local_est_GPS_time = float(values['TimeNanos']) - (fullbiasnanos + float(values['BiasNanos']))
        gpssow = local_est_GPS_time * NS_TO_S - gpsweek * GPS_WEEKSECS

        # Fractional part of the integer seconds
        frac = 0.0

        if args.integerize:
            frac = gpssow - int(gpssow+0.5)

        # Convert the epoch to Python's buiit-in datetime class
        epoch = gpstime_to_epoch(gpsweek, gpssow-frac)

        # Check for first epoch, that will be used to end the header (to
        # print the cumpolsory TIME OF FIRST OBS field)
        if first_epoch is None:
            out.write(end_header(epoch))
            first_epoch = False

        # Check if we need to create a new batch
        if rinex_batch is None:
            rinex_batch = RinexBatch(epoch)

        elif rinex_batch.epoch != epoch:

            out.write(rinex_batch.print())
            rinex_batch = RinexBatch(epoch)

        #pseudorange
        #???????????????????????????????????????????????????????????? is the number of nanoseconds that have occurred from the beginning of GPS time to the current WN.
        #???????????????????????????????????????????????????????? is the number of nanoseconds that have occurred from the beginning of GPS time to the current day.
        #???????????????????????????????????????????????????????????????????????????????????????????? is the number of milliseconds that have occurred from the beginning of the GPS time.
        week_number_nanos = math.floor(-fullbiasnanos / NUM_NANOSEC_WEEK) * NUM_NANOSEC_WEEK
        day_number_nanos = math.floor(-fullbiasnanos / NUM_NANOSEC_DAY) * NUM_NANOSEC_DAY
        millSec_number_nanos = math.floor(-fullbiasnanos / NUM_NANOSEC_100MILL) * NUM_NANOSEC_100MILL

        #tRx_GNSS = TimeNanos + TimeOffsetNanos - FullBiasNanos - BiasNanos;
        tRx_GNSS = float(values['TimeNanos']) + float(values['TimeOffsetNanos']) - float(values['FullBiasNanos']) - float(values['BiasNanos'])

        if values['LeapSecond'] is None:
            values['LeapSecond'] = "0"

        if int(values['ConstellationType']) == CONSTELLATION_GPS:
            tRx_nanos = tRx_GNSS - week_number_nanos
        elif int(values['ConstellationType']) == CONSTELLATION_GLONASS:
            tRx_nanos = tRx_GNSS - day_number_nanos + (3*3600 - int(values['LeapSecond'])) * S_TO_NS
        elif int(values['ConstellationType']) == CONSTELLATION_GALILEO:
            if float(values['CarrierFrequencyHz']) > 1500e6:
                tRx_nanos = tRx_GNSS - millSec_number_nanos
            else:
                tRx_nanos = tRx_GNSS - week_number_nanos
        elif int(values['ConstellationType']) == CONSTELLATION_BEIDOU:
            tRx_nanos = tRx_GNSS - week_number_nanos - 14 * S_TO_NS
        else:
            tRx_nanos = tRx_GNSS - week_number_nanos

        # # Populate missing fields that are needed to remove fractional offsets
        # # from reception time
        # if values['TimeOffsetNanos'] is None:
        #     values['TimeOffsetNanos'] = 0.0

        # if values['BiasNanos'] is None:
        #     values['BiasNanos'] = 0.0

        # # Compute the reception and transmission times
        # tRxSeconds = gpssow - values['TimeOffsetNanos'] * NS_TO_S
        tRxSeconds = tRx_nanos * NS_TO_S
        tTxSeconds = float(values['ReceivedSvTimeNanos']) * NS_TO_S

        # Compute the travel time, which will be eventually the pseudorange
        tau = tRxSeconds - tTxSeconds

        #??Check the week rollover, for measurements near the week transition
        if tau < 0:
            tau += GPS_WEEKSECS

        # Compute the range as the difference between the received time and
        # the transmitted time
        c1 = tau * SPEED_OF_LIGHT 
        
        # Check if the range needs to be modified with the range rate in
        # order to make it consistent with the timestamp
        if args.integerize:
            c1 -= frac * float(values['PseudorangeRateMetersPerSecond'])

        # Add measurements into the batch (to be printed when the data changes epoch)
        svid = ''
        codeType = ''
        l1 = 0
        d1 = 0
        prn = int(values['Svid'])

        #Warning : some of the measurement data don't have CarrierFrequencyHz, maybe get wrong in this step.
        if values['CarrierFrequencyHz'] is None:
            values['CarrierFrequencyHz'] = "2000e6"


        if int(values['ConstellationType']) == CONSTELLATION_GPS:
            svid = 'G{0:02d}'.format(prn)

            #judge what code type is it.
            if float(values['CarrierFrequencyHz']) > 1500e6:
                codeType = "L1"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GPS_L1_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GPS_L1_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GPS_L1_WAVELENGTH
            elif float(values['CarrierFrequencyHz']) > 1200e6:
                codeType = "L2"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GPS_L2_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GPS_L2_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GPS_L2_WAVELENGTH
            elif float(values['CarrierFrequencyHz']) > 1100e6:
                codeType = "L5"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GPS_L5_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GPS_L5_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GPS_L5_WAVELENGTH

        elif int(values['ConstellationType']) == CONSTELLATION_GLONASS:
            if int(values['Svid']) >= 93:
                sys.stderr.write("Receiver is giving Frequency slot number (FSN) "+
                                 "instead of Orbital Slot Number (OSN). Since " +
                                 "I have no means of converting between them, "+
                                 "I am going to skip this measurement\n")
                continue
            else:
                svid = 'R{0:02d}'.format(prn)

            #judge what code type is it.
            if float(values['CarrierFrequencyHz']) > 1500e6:
                codeType = "L1"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / get_glo_L1(GLN_LIST[prn-1])
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, get_glo_L1(GLN_LIST[prn-1]))

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / get_glo_L1(GLN_LIST[prn-1])
            elif float(values['CarrierFrequencyHz']) > 1200e6:
                codeType = "L2"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / get_glo_L2(GLN_LIST[prn-1])
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, get_glo_L2(GLN_LIST[prn-1]))

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / get_glo_L2(GLN_LIST[prn-1])

        elif int(values['ConstellationType']) == CONSTELLATION_GALILEO:
            svid = 'E{0:02d}'.format(prn)

            #judge what code type is it.
            if float(values['CarrierFrequencyHz']) > 1500e6:
                codeType = "E1"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GAL_E1_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GAL_E1_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GAL_E1_WAVELENGTH
            elif float(values['CarrierFrequencyHz']) > 1250e6:
                codeType = "E6"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GAL_E6_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GAL_E6_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GAL_E5B_WAVELENGTH
            elif float(values['CarrierFrequencyHz']) > 1200e6:
                codeType = "E5b"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GAL_E5B_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GAL_E5B_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GAL_E5B_WAVELENGTH
            elif float(values['CarrierFrequencyHz']) > 1100e6:
                codeType = "E5a"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / GAL_E5A_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, GAL_E5A_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / GAL_E5A_WAVELENGTH

        elif int(values['ConstellationType']) == CONSTELLATION_BEIDOU:
            svid = 'C{0:02d}'.format(prn)

            #judge what code type is it.
            if float(values['CarrierFrequencyHz']) > 1500e6:
                codeType = "B1"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / BDS_L1_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, BDS_L1_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / BDS_L1_WAVELENGTH
            elif values['CarrierFrequencyHz'] > 1250e6:
                codeType = "B3"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / BDS_L3_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, BDS_L3_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / BDS_L3_WAVELENGTH
            elif values['CarrierFrequencyHz'] > 1100e6:
                codeType = "B2"
                #adr (cycles)
                l1 = values['AccumulatedDeltaRangeMeters'] / BDS_L2_WAVELENGTH
                #corrected adr (cycles)
                l1 = get_correction_adr(c1, l1, BDS_L2_WAVELENGTH)

                d1 = - float(values['PseudorangeRateMetersPerSecond']) / BDS_L2_WAVELENGTH

        elif int(values['ConstellationType']) == CONSTELLATION_QZSS:
            sys.stderr.write("Constellation SBAS not supported\n")
            continue
        elif int(values['ConstellationType']) == CONSTELLATION_SBAS:
            sys.stderr.write("Constellation SBAS not supported\n")
            continue
        else:
            sys.stderr.write("Constellation unknown. Skipping\n")
            continue

        try:
            check_adr_state(int(values['AccumulatedDeltaRangeState']))
        except ValueError as e:
            sys.stderr.write("-- WARNING: {0} for satellite [ {1} ]\n".format(e, svid))
            l1 = 0

        # Minimum data quality edition
        # if not args.skip_edit:
        #     sys.stderr.write("Measurement [ {0} ] for svid [ {1} ] rejected. Out of bounds\n".format(svid, c1))
        #     continue

        #??Process the accumulated delta range (i.e. carrier phase). This
        # needs to be translated from meters to cycles (i.e. RINEX format
        # specification)
        s1 = float(values['Cn0DbHz'])

        # If we reached this point it means that all went well. Therefore
        # proceed to store the measurements
        rinex_batch.add(codeType, svid, '{:.3f}'.format(c1), '{:.3f}'.format(s1), '{:.3f}'.format(l1), '{:.3f}'.format(d1))

       
    # Print last batch
    out.write(rinex_batch.print())

    fh.close()
    out.close()

