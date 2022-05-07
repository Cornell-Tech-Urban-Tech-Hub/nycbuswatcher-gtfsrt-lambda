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
    aws_secret_name="LambdaDeveloperKeys"
    aws_access_key_id = get_secret(aws_secret_name,aws_region_name)['aws_access_key_id']
    aws_secret_access_key = get_secret(aws_secret_name,aws_region_name)['aws_secret_access_key']
    
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
    
    # convert timestamp
    positions_df['vehicle.timestamp'] = pd.to_datetime(positions_df['vehicle.timestamp'], unit="s")
    
    # # this is essential or else pd.to_parquet dies without warning
    # positions_df['vehicle.timestamp'] = positions_df['vehicle.timestamp'].dt.tz_localize(None)
    
    ################################################################## 
    # dump S3 as parquet
    ##################################################################   
    
    # dump to instance ephemeral storage 
    timestamp = dt.datetime.now().replace(microsecond=0)
    filename=f"{system_id}_{timestamp}.parquet".replace(" ", "_").replace(":", "_")

    #FIXME: its clear we are running out of memory, but can't seem to increase it (at least on desktop)
    positions_df.to_parquet(f"/tmp/{filename}", times='int96')

    # upload to S3
    source_path=f"/tmp/{filename}" 
    remote_path=f"{system_id}/{filename}"  

    session = boto3.Session(
        region_name=aws_region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key)
    s3 = session.resource('s3')
    result = s3.Bucket(aws_bucket_name).upload_file(source_path,remote_path)

    
    # report back to invoker
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"done. wrote {positions_df['route_short'].nunique()} routes and {len(positions_df)} buses to S3.",
        }),
    }    
