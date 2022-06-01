import json
from secret_helper import get_secret
from google.transit import gtfs_realtime_pb2
from protobuf_to_dict import protobuf_to_dict
import pandas as pd
import requests
import datetime as dt
import boto3


def lambda_handler(event, context):

    ################################################################## 
    # configuration
    ################################################################## 

    # aws
    aws_bucket_name="busobservatory"
    aws_region_name="us-east-1"
    
    # system to track
    # store api key in secret api_key_{system_id}
    # e.g. api_key_nyct_mta_bus_siri
    system_id="nyct_mta_bus_gtfsrt"
    mta_bustime_api_key = get_secret(f'api_key_{system_id}', aws_region_name)['agency_api_key']

    # endpoint
    url_GTFSRT = "http://gtfsrt.prod.obanyc.com/vehiclePositions?key={}"

    ################################################################## 
    # fetch data
    ##################################################################   
 
    response = requests.get(
        url_GTFSRT.format(mta_bustime_api_key)
        )

    ################################################################## 
    # parse data
    ##################################################################

    # flatten data
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    
    # convert protobuf to dict
    buses_dict = protobuf_to_dict(feed) 

    # convert dict to dataframe
    positions_df=pd.json_normalize(buses_dict['entity'])
    
    # convert timestamp is 4 steps to get local time recorded properly in parquet
    # 1 convert POSIX timestamp to datetime
    positions_df['vehicle.timestamp'] = pd.to_datetime(positions_df['vehicle.timestamp'], unit="s")
    # 2 tell pandas its UTC
    positions_df['vehicle.timestamp'] = positions_df['vehicle.timestamp'].dt.tz_localize('UTC')
    # 3 convert the offset to local time #FIXME: should timezone this from os.environ['TZ']
    positions_df['vehicle.timestamp'] = positions_df['vehicle.timestamp'].dt.tz_convert('America/New_York')
    # 4 make naive again (not sure why this is needed)
    positions_df['vehicle.timestamp'] = positions_df['vehicle.timestamp'].dt.tz_localize(None)

    ################################################################## 
    # dump S3 as parquet
    ##################################################################   
    
    # dump to instance ephemeral storage 
    timestamp = dt.datetime.now().replace(microsecond=0)
    filename=f"{system_id}_{timestamp}.parquet".replace(" ", "_").replace(":", "_")

    # positions_df.to_parquet(f"/tmp/{filename}", times='int96')
    positions_df.to_parquet(f"/tmp/{filename}", times='int96')

    # upload to S3
    source_path=f"/tmp/{filename}" 
    remote_path=f"{system_id}/{filename}"  

    session = boto3.Session(region_name=aws_region_name)
    s3 = session.resource('s3')
    result = s3.Bucket(aws_bucket_name).upload_file(source_path,remote_path)

    
    # report back to invoker
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"nycbuswatcher-gtfsrt-lambda: wrote {positions_df['vehicle.trip.route_id'].nunique()} routes and {len(positions_df)} buses to S3.",
        }),
    }    
