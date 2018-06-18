'''
Created on Jun 8, 2018

@author: runshengsong
'''
# TO DO
# move settings to config
import os
import sys
import boto3
import base64
import numpy as np

def base64_encode_image(a):
    """
    encode the image
    """
    # base64 encode the input NumPy array
    return base64.b64encode(a).decode("utf-8")

def base64_decode_image(a, dtype, shape):
    """
    decode the image
    """
    # convert the string to a NumPy array using the supplied data
    # type and target shape
    a = np.frombuffer(base64.decodestring(a), dtype=dtype)
    a = a.reshape(shape)

    # return the decoded image
    return a

def download_a_dir_from_s3(bucket_name, bucket_prefix, local_path):
    """
    download the folder from S3 
    
    local: /src/tmp/model_data/
    """
    print "* Helper: Loading Images from S3 {} {}".format(bucket_name,bucket_prefix)
    s3 = boto3.resource('s3')
    mybucket = s3.Bucket(bucket_name)
    # if blank prefix is given, return everything)
    objs = mybucket.objects.filter(
        Prefix = bucket_prefix)
    
    for obj in objs:
        path, filename = os.path.split(obj.key)
        save_path = os.path.join(local_path, path)
        # boto3 s3 download_file will throw exception if folder not exists
        try:
            os.makedirs(save_path)
        except OSError:
            pass
        mybucket.download_file(obj.key, os.path.join(save_path, filename))
        
    # move the folder to target place
    output_path = os.path.join(local_path, bucket_prefix)
    print "* Helper: Images Loaded at: {}".format(output_path)
    return output_path
    
    