# Copyright 2020 Wearless Tech Inc All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import av
import time
import os
import io
from av.filter import Filter, Graph
from av.codec import CodecContext
import redis
import threading, queue
from read_image import ReadImage
import random
from argparse import ArgumentParser
import sys
from archive import StoreMP4VideoChunks
from global_vars import query_timestamp, RedisIsKeyFrameOnlyPrefix, RedisLastAccessPrefix, ArchivePacketGroup


class RTSPtoRTMP(threading.Thread):

    def __init__(self, rtsp_endpoint, rtmp_endpoint, packet_queue, device_id, disk_path, redis_conn, is_decode_packets_event, lock_condition):
        threading.Thread.__init__(self) 
        self._packet_queue = packet_queue
        self._disk_path = disk_path
        self.rtsp_endpoint = rtsp_endpoint
        self.rtmp_endpoint = rtmp_endpoint
        self.redis_conn = redis_conn
        self.device_id = device_id
        self.is_decode_packets_event = is_decode_packets_event
        self.lock_condition = lock_condition
        self.query_timestamp = query_timestamp

    def link_nodes(self,*nodes):
        for c, n in zip(nodes, nodes[1:]):
            c.link_to(n)

    def run(self):
        global RedisLastAccessPrefix    

        current_packet_group = []
        flush_current_packet_group = False

        # init archiving 
        iframe_start_timestamp = 0
        packet_group_queue = queue.Queue()

        should_mux = False

        while True:
            try:
                options = {'rtsp_transport': 'tcp', 'stimeout': '5000000', 'max_delay': '5000000', 'use_wallclock_as_timestamps':"1", "fflags":"+genpts", 'acodec':'aac'}
                self.in_container = av.open(self.rtsp_endpoint, options=options)
                self.in_video_stream = self.in_container.streams.video[0]
                self.in_audio_stream = None
                if len(self.in_container.streams.audio) > 0:
                    self.in_audio_stream = self.in_container.streams.audio[0]

                # init mp4 local archive
                if self._disk_path is not None:
                    self._mp4archive = StoreMP4VideoChunks(queue=packet_group_queue, path=self._disk_path, device_id=self.device_id, video_stream=self.in_video_stream, audio_stream=self.in_audio_stream)
                    self._mp4archive.daemon = True
                    self._mp4archive.start()

            except Exception as ex:
                print("failed to connect to RTSP camera", ex)
                os._exit(1)
            
            keyframe_found = False
            global query_timestamp

            if self.rtmp_endpoint is not None:
                output = av.open(self.rtmp_endpoint, format="flv", mode='w')
                output_video_stream = output.add_stream(template=self.in_video_stream)  

            output_audio_stream = None
            if self.in_audio_stream is not None and self.rtmp_endpoint is not None:
                output_audio_stream = output.add_stream(template=self.in_audio_stream)


            for packet in self.in_container.demux(self.in_video_stream):

                if packet.dts is None:
                    continue
                
                if packet.is_keyframe:
                    # if we already found a keyframe previously, archive what we have

                    if len(current_packet_group) > 0:
                        packet_group = current_packet_group.copy()
                        
                        # send to archiver! (packet_group, iframe_start_timestamp)
                        if self._disk_path is not None:
                            apg = ArchivePacketGroup(packet_group, iframe_start_timestamp)
                            packet_group_queue.put(apg)

                    keyframe_found = True
                    current_packet_group = []
                    iframe_start_timestamp = int(round(time.time() * 1000))

                if keyframe_found == False:
                    print("skipping, since not a keyframe")
                    continue
                
                # shouldn't be a problem for redis but maybe every 200ms to query for latest timestamp only
                settings_dict = self.redis_conn.hgetall(RedisLastAccessPrefix + device_id)

                if settings_dict is not None and len(settings_dict) > 0:
                    settings_dict = { y.decode('utf-8'): settings_dict.get(y).decode('utf-8') for y in settings_dict.keys() } 
                    if "last_query" in settings_dict:
                        ts = settings_dict['last_query']
                    else:
                        continue
                    
                    # check if stream should be forwarded to Chrysalis Cloud RTMP
                    if "proxy_rtmp" in settings_dict:
                        should_mux_string = settings_dict['proxy_rtmp']
                        previous_should_mux = should_mux
                        if should_mux_string == "1":
                            should_mux = True
                        else:
                            should_mux = False
                    
                        # check if it's time for flushing of current_packet_group 
                        if should_mux != previous_should_mux and should_mux == True:
                            flush_current_packet_group = True
                        else:
                            flush_current_packet_group = False
                    
                    ts = int(ts)
                    ts_now = int(round(time.time() * 1000))
                    diff = ts_now - ts
                    # if no request in 10 seconds, stop
                    if diff < 10000:
                        try:
                            self.lock_condition.acquire()
                            query_timestamp = ts
                            self.lock_condition.notify_all()
                        finally:
                            self.lock_condition.release() 

                        self.is_decode_packets_event.set()

                if packet.is_keyframe:
                    self.is_decode_packets_event.clear()
                    self._packet_queue.queue.clear()
                
                
                self._packet_queue.put(packet)

                try:
                    if self.rtmp_endpoint is not None and should_mux:
                        # flush is necessary current_packet_group (start/stop RTMP stream)
                        if flush_current_packet_group:
                            for p in current_packet_group:
                                if p.stream.type == "video":
                                    p.stream = output_video_stream
                                    output.mux(p)
                                if p.stream.type == "audio":
                                    p.stream = output_audio_stream
                                    output.mux(p)

                        if packet.stream.type == "video":
                            packet.stream = output_video_stream
                            output.mux(packet)            
                        if packet.stream.type == "audio":
                            if output_audio_stream is not None:
                                packet.stream = output_audio_stream
                                output.mux(packet)
                except Exception as e:
                    print("failed muxing", e)

                current_packet_group.append(packet)
            
            time.sleep(1) # wait a second before trying to get more packets
            print("rtsp stopped streaming...waiting for camera to reappear")
        


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--rtsp", type=str, default=None, required=True)
    parser.add_argument("--rtmp", type=str, default=None, required=False)
    parser.add_argument("--device_id", type=str, default=None, required=True)
    parser.add_argument("--memory_buffer", type=int, default=1, required=False)
    parser.add_argument("--disk_path", type=str, default=None, required=False)

    args = parser.parse_args()

    rtmp = args.rtmp
    rtsp = args.rtsp
    device_id = args.device_id
    memory_buffer=args.memory_buffer
    disk_path=args.disk_path

    decode_packet = threading.Event()
    lock_condition = threading.Condition()
    
    print("RTPS Endpoint: ",rtsp)
    print("RTMP Endpoint: ", rtmp)
    print("Device ID: ", device_id)
    print("memory buffer: ", memory_buffer)
    print("disk path: ", disk_path)

    redis_conn = None
    try:
        pool = redis.ConnectionPool(host="redis", port="6379")
        # pool = redis.ConnectionPool(host="localhost", port="6379")
        redis_conn = redis.Redis(connection_pool=pool)
    except Exception as ex:
        print("failed to connect to redis instance", ex)
        sys.exit("failed to connec to redis server")

    # Test redis connection
    ts = redis_conn.hgetall(RedisLastAccessPrefix + device_id)
    print("last query time: ", ts)

    get_images = False
    packet_queue = queue.Queue()

    th = RTSPtoRTMP(rtsp_endpoint=rtsp, 
                    rtmp_endpoint=rtmp, 
                    packet_queue=packet_queue, 
                    device_id=device_id,
                    disk_path=disk_path, 
                    redis_conn=redis_conn, 
                    is_decode_packets_event=decode_packet, 
                    lock_condition=lock_condition)
    th.daemon = True
    th.start()

    ri = ReadImage(packet_queue=packet_queue, 
        device_id=device_id, 
        memory_buffer=memory_buffer,
        redis_conn=redis_conn, 
        is_decode_packets_event=decode_packet, 
        lock_condition=lock_condition)
    ri.daemon = True
    ri.start()
    ri.join()
    
    th.join()