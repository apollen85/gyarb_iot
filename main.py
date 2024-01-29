import datetime
from scd4x import SCD4X

import os
import time
import board
import busio
import adafruit_sgp30
import RPi.GPIO as GPIO

# Delay if you do not want the unit to begin measuring directly
# time.sleep(7800)

CLASSROOM = "a152"
DATA_FILE = "data.txt" # For storing baseline values (not the collected data)
DO_CALIBRATION = False
CALIBRATION_ENV = "in" # Can be out/in. Out is 10min, in is 12h
API_KEY = "REDACTED" # Redacted.


# Pins for magnetic switches. No switches connected
SW_DOOR = 4
SW_WINDOW = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(SW_DOOR, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(SW_WINDOW, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Write the given baseline values to the file. isCalibrating should be True if the measurement is not fully calibrated. It adds a note in the file
def writeBaseValues(eCO2_base_infunc, TVOC_base_infunc, isCalibrating):
    dataFile = open(DATA_FILE, "a")
    dataFile.write("\n\n")
    if isCalibrating == True:
        dataFile.write("IS_CALIBRATING\n")
    dataFile.write("Timestamp:" + str(time.time()) + "\n")
    dataFile.write("Datetime:" + str(datetime.datetime.now()) + "\n")
    dataFile.write("eCO2:" + str(eCO2_base_infunc) + "\n")
    dataFile.write("TVOC:" + str(TVOC_base_infunc) + "\n")
    dataFile.close()

    print("-----------------Wrote new baseline values---------------")
    print("eCO2_base:"+ str(eCO2_base_infunc)+"  TVOC_base:"+ str(TVOC_base_infunc))
    print("---------------End wrote new baseline values-------------")

# Get the latest recorded baseline values from the file
def getLatestBaseValues():
    dataFile = open(DATA_FILE, "r")
    lines = dataFile.readlines()
    dataFile.close()
    lines = lines[-2:]

    # eCO2
    params = lines[0].split(":")
    eCO2_base_infunc = int(params[1])

    # TVOC
    params = lines[1].split(":")
    TVOC_base_infunc = int(params[1])

    print("------------Read new baseline values---------------")
    print("eCO2_base:"+ str(eCO2_base_infunc)+"  TVOC_base:"+ str(TVOC_base_infunc))
    print("------------End new baseline reading---------------")
    
    return eCO2_base_infunc, TVOC_base_infunc

# Returns the amount of time since last stored calibration data point
# Format specifies s, m, h or d (seconds, minutes, hours, days)
def getTimeSinceCalibration(format):
    dataFile = open(DATA_FILE, "r")
    lines = dataFile.readlines()
    dataFile.close()
    timeLine = lines[-4] # Probably incorrect
    oldTime = float(timeLine.split(":")[1])
    diff = time.time() - oldTime
    if format=="m" or format=="h" or format=="d":
        diff = diff/60
        if format=="h" or format=="d":
            diff = diff/60
            if format=="d":
                diff = diff/24
    
    return diff

# Send data to IoT Open Lynx platform
def sendData(valueType, value):
    valueType = CLASSROOM + "-" + valueType
    os.system(r"""mosquitto_pub -h "lynx-jkpg.iotopen.se" -p 8883 -u "usr" -P "%s" -t "183/obj/%s" -m "{ \"value\": %.4f }" """%(API_KEY, valueType, value))
    print("Sent valueType:" + valueType + "    value:" + str(value))

# True if door open
def getDoorOpen():
    return not GPIO.input(SW_DOOR) # gpio is high if switch is closed. If switch is closed the door is closed.

# True if window open
def getWindowOpen():
    return not GPIO.input(SW_WINDOW) # gpio is high if switch is closed. If switch is closed the window is closed.

# Returns true if change was detected
def checkDoor():
    doorState = getDoorOpen()
    if doorState != prevDoorState:
        return True
    else:
        return False

# Returns true if change was detected
def checkWindow():
    windowState = getWindowOpen()
    if windowState != prevWindowState:
        return True
    else:
        return False



sens_co2 = device = SCD4X(quiet=False)
sens_co2.start_periodic_measurement()

eCO2_base = 0
TVOC_base = 0

i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
sgp30 = adafruit_sgp30.Adafruit_SGP30(i2c)
eCO2_base = 0
TVOC_base = 0
# sgp30.set_iaq_baseline(37195, 37419)
if DO_CALIBRATION == False:
    eCO2_base, TVOC_base = getLatestBaseValues()
    sgp30.set_iaq_baseline(eCO2_base, TVOC_base)
else:
    pass # Do not set any baseline if calibration should be performed
sgp30.set_iaq_relative_humidity(celsius=20.0 , relative_humidity=50)



# Setting timeflags
startTime = time.time()
baselineTimeFlag = startTime
normalTimeFlag = startTime
dataSendTimeFlag = startTime
co2TimeFlag = startTime

# Settings time intervals
calibrationTime = 43200 # 12h in seconds
baselineLoggingTime = 3600 # Log baseline values every 60 minutes (3600 seconds)
co2IntervalTime = 6 # interval between CO2 readings
dataSendIntervalTime = 60 # send data every minute

# Momentary values
CO2 = 0
temperature = 0
relative_humidity = 0
eCO2 = 0
TVOC = 0
timestamp = 0
doorState = getDoorOpen()
prevDoorState = not doorState # Set to not to force update
windowState = getWindowOpen()
prevWindowState = not windowState # Set to not to force update

# Sums for mean calculation
sum_CO2 = 0 
sum_temperature = 0
sum_relative_humidity = 0
sum_eCO2 = 0
sum_TVOC = 0

# Measurement counts for mean calculation
scd41_meas_count = 0
sgp30_meas_count = 0

# Mean calculation
mean_CO2 =CO2 
mean_temperature = temperature
mean_relative_humidity = relative_humidity
mean_eCO2 = eCO2 
mean_TVOC = TVOC

# Tells the program that we are on the first loop and should not send data
firstLoop = True


# Calibration logic
if DO_CALIBRATION == True:
    if CALIBRATION_ENV == "in":
        calibrationTime = 60*60*12 # 12 hours
    elif CALIBRATION_ENV == "out":
        calibrationTime = 60*12 # 12 minutes (10 should be sufficient, but why not have 12)
    else:
        print("Error: Invalid value for CALIBRATION_ENV")
        quit()


    


# Main loop - goes on forever
while True:
    
    # Loop in the loop. Everything executes once a second
    if time.time()-normalTimeFlag > 1:

        # Setting time flag
        normalTimeFlag = time.time()

        # SGP30
        eCO2, TVOC = sgp30.iaq_measure()
        sum_eCO2 += eCO2
        sum_TVOC += TVOC
        sgp30_meas_count += 1

        # Check magnetic contacts
        if checkDoor() == True:
            doorState = getDoorOpen()
            prevDoorState = doorState
            sendData("door", not doorState) # Inverted to comply with IoT platform rules
        if checkWindow() == True:
            windowState = getWindowOpen()
            prevWindowState = windowState
            sendData("window", not windowState) # Inverted to comply with IoT platform rules

        # Update scd41 every co2IntervalTime seconds
        if time.time()-co2TimeFlag > co2IntervalTime:
            CO2, temperature, relative_humidity, timestamp = sens_co2.measure()
            sum_CO2 += CO2
            sum_temperature += temperature
            sum_relative_humidity += relative_humidity
            scd41_meas_count += 1
            co2TimeFlag = time.time()

        # Print values to terminal (mostly for debugging)
        # print(f"""
        # Timestamp:   {timestamp}
        # CO2:         {CO2:.2f}PPM
        # Temperature: {temperature:.4f}c
        # Humidity:    {relative_humidity:.2f}%RH
        # TVOC:        {TVOC}ppb
        # eCO2:        {eCO2:.2f}ppm""")
    
        # Calculating values, sending them and updating sgp30 parameters
        if time.time()-dataSendTimeFlag > dataSendIntervalTime:
            # Calculate values
            mean_CO2 = sum_CO2/scd41_meas_count
            mean_temperature = sum_temperature/scd41_meas_count
            mean_relative_humidity = sum_relative_humidity/scd41_meas_count
            mean_eCO2 = sum_eCO2/sgp30_meas_count
            mean_TVOC = sum_TVOC/sgp30_meas_count

            # Do not run these things first loop due to bad readings
            if firstLoop == False:

                # Send values
                sendData("co2", mean_CO2)
                sendData("temperature", mean_temperature)
                sendData("rh", mean_relative_humidity)
                sendData("eco2", mean_eCO2)
                sendData("tvoc", mean_TVOC)
                
                #Update sgp30
                sgp30.set_iaq_relative_humidity(celsius=mean_temperature, relative_humidity=mean_relative_humidity) # Update these values every minute
                
            # Prepare for next time
            sgp30.set_iaq_relative_humidity(celsius=temperature , relative_humidity=relative_humidity)
            sum_CO2 = 0
            sum_temperature = 0
            sum_relative_humidity = 0
            sum_eCO2 = 0
            sum_TVOC = 0
            scd41_meas_count = 0
            sgp30_meas_count = 0
            firstLoop = False
            dataSendTimeFlag = time.time()

        # Save base values every hour. Should this also be done during calibration?
        if time.time()-baselineTimeFlag > baselineLoggingTime:
            eCO2_base, TVOC_base = sgp30.get_iaq_baseline()
            writeBaseValues(eCO2_base, TVOC_base, DO_CALIBRATION)
            baselineTimeFlag = time.time()
        
        # If the calibration time has passed, write baseline values regardless of the saving every hour
        if DO_CALIBRATION == True and time.time()-startTime > calibrationTime:
            eCO2_base, TVOC_base = sgp30.get_iaq_baseline()
            writeBaseValues(eCO2_base, TVOC_base, False)
            DO_CALIBRATION = False # Make sure that this code is not executed again

    # Do nothing if we are not on a whole second
    else:
        pass
