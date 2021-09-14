# coding=utf-8
# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import datetime
import torch
import json
from flask import Flask, request, jsonify, current_app
from flask_restful import Resource, Api
from megatron import get_args
from megatron import mpu
from megatron.text_generation_utils import generate

GENERATE_NUM = 0

class MegatronGenerate(Resource):
    def __init__(self, model):
        self.model = model
    
    @staticmethod
    def send_do_generate():
        choice = torch.cuda.LongTensor([GENERATE_NUM])
        torch.distributed.broadcast(choice,
                                    mpu.get_tensor_model_parallel_src_rank(),
                                    group=mpu.get_tensor_model_parallel_group())
     
    def put(self):
        args = get_args()
        print("request IP: " + str(request.remote_addr))
        print(json.dumps(request.get_json()),flush=True)
        print("current time: ", datetime.datetime.now())
        sentences = request.get_json()["sentences"]
        if len(sentences) > 128:
            return "Maximum number of sentences is 128", 400

        tokens_to_generate = 64  # Choosing hopefully sane default.  Full sequence is slow
        if "tokens_to_generate" in request.get_json():
            tokens_to_generate = request.get_json()["tokens_to_generate"]
            if not isinstance(tokens_to_generate, int):
                return "tokens_to_generate must be an integer greater than 0"
            if tokens_to_generate < 1:
                return "tokens_to_generate must be an integer greater than 0"

        all_probs = False
        if "all_probs" in request.get_json():
            all_probs = request.get_json()["all_probs"]
            if not isinstance(all_probs, bool):
                return "all_probs must be a boolean value"

        MegatronGenerate.send_do_generate()  # Tell other ranks we're doing generate
        resp_sentences, resp_sentences_seg, output_logits, full_logits, tokens = generate(self.model, sentences, tokens_to_generate, all_probs) 
        if all_probs:
            return jsonify({"sentences": resp_sentences,
                "segments": resp_sentences_seg,
                "logits": output_logits,
                "all_logits": full_logits,
                "tokens": tokens})
        
        return jsonify({"sentences": resp_sentences,
            "segments": resp_sentences_seg,
            "logits": output_logits})

class MegatronServer(object):
    def __init__(self, model):
        self.app = Flask(__name__, static_folder='static', static_url_path='')
        self.app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
        api = Api(self.app)
        api.add_resource(MegatronGenerate, '/generate', resource_class_args=[model])

    def run(self, url):
        self.app.run(url, threaded=True, debug=False)
