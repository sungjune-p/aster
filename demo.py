import os
import logging
import tensorflow as tf
from PIL import Image
from google.protobuf import text_format
import numpy as np

from aster.protos import pipeline_pb2
from aster.builders import model_builder
from pymongo import MongoClient
import pymongo
import csv


# Connect mongo database
client = MongoClient('mongo', 27017)
db = client.testdb
col = db.scene_text
col.remove({})

# supress TF logging duplicates
logging.getLogger('tensorflow').propagate = False
tf.logging.set_verbosity(tf.logging.INFO)
logging.basicConfig(level=logging.INFO)

flags = tf.app.flags
flags.DEFINE_string('exp_dir', 'aster/experiments/demo/',
                    'Directory containing config, training log and evaluations')
# flags.DEFINE_string('input_image', 'aster/data/demo.jpg', 'Demo image')

########## Adjust directory path ##########
flags.DEFINE_string('data_dir', 'aster/data/test_images', 'Input Cropped Images')
flags.DEFINE_string('tsv_dir', 'aster/data/tsvs', 'Input .tsv file directory')
########## Adjust directory path ##########

FLAGS = flags.FLAGS


def get_configs_from_exp_dir():
    pipeline_config_path = os.path.join(FLAGS.exp_dir, 'config/trainval.prototxt')

    pipeline_config = pipeline_pb2.TrainEvalPipelineConfig()
    with tf.gfile.GFile(pipeline_config_path, 'r') as f:
        text_format.Merge(f.read(), pipeline_config)

    model_config = pipeline_config.model
    eval_config = pipeline_config.eval_config
    input_config = pipeline_config.eval_input_reader

    return model_config, eval_config, input_config


def main(_):
    checkpoint_dir = os.path.join(FLAGS.exp_dir, 'log')
    # eval_dir = os.path.join(FLAGS.exp_dir, 'log/eval')
    model_config, _, _ = get_configs_from_exp_dir()

    model = model_builder.build(model_config, is_training=False)

    input_image_str_tensor = tf.placeholder(dtype=tf.string, shape=[])
    input_image_tensor = tf.image.decode_jpeg(input_image_str_tensor, channels=3, )
    resized_image_tensor = tf.image.resize_images(tf.to_float(input_image_tensor), [64, 256])

    predictions_dict = model.predict(tf.expand_dims(resized_image_tensor, 0))
    recognitions = model.postprocess(predictions_dict)
    recognition_text = recognitions['text'][0]
    control_points = predictions_dict['control_points'],
    rectified_images = predictions_dict['rectified_images']

    saver = tf.train.Saver(tf.global_variables())
    checkpoint = os.path.join(FLAGS.exp_dir, 'log/model.ckpt')

    fetches = { 'original_image': input_image_tensor, 'recognition_text': recognition_text, 'control_points': predictions_dict['control_points'], 'rectified_images': predictions_dict['rectified_images'], }

    with tf.Session() as sess:
        sess.run([tf.global_variables_initializer(), tf.local_variables_initializer(), tf.tables_initializer()])
        saver.restore(sess, checkpoint)

        image_list = os.listdir(FLAGS.data_dir)
        image_list.sort()
        vid_num = '00000'
        for file in image_list:
            with open(os.path.join(FLAGS.data_dir, file), 'rb') as f:
                input_image_str = f.read()
            
            # Read .tsv file to get frame info
            if vid_num != file.split('_')[0][4:]:
                tsv_path = os.path.join(FLAGS.tsv_dir, file.split('_')[0][4:]+'.tsv')
                with open(tsv_path) as tsv_file:
                    tsv_reader = csv.reader(tsv_file, delimiter="\t")
                    frame_data = []
                    i = 0
                    for line in tsv_reader:
                        if i == 0:
                            pass
                        else:
                            frame_data.append(line)
                        i += 1

            sess_outputs = sess.run(fetches, feed_dict={input_image_str_tensor: input_image_str})
            text = sess_outputs['recognition_text'].decode('utf-8')

            print('Recognized text for ',file,' : {}'.format(sess_outputs['recognition_text'].decode('utf-8')))

        # rectified_image = sess_outputs['rectified_images'][0]
        # rectified_image_pil = Image.fromarray((128 * (rectified_image + 1.0)).astype(np.uint8))
        # input_image_dir = os.path.dirname(FLAGS.input_image)
        # rectified_image_save_path = os.path.join(FLAGS.data_dir, 'rectifed %s' %file)
        # rectified_image_pil.save(rectified_image_save_path)
        # print('Rectified image saved to {}'.format(rectified_image_save_path))
        # print('Check Video Number : ', file.split('_')[0])
            print('Check Image Name : ', '_'.join([file.split('_')[0], file.split('_')[1]]))
            video_number = int(file.split('_')[0][4:])
            key_frame_num = int(file.split('_')[1])
            start_frame = int(frame_data[key_frame_num - 1][0])
            end_frame = int(frame_data[key_frame_num - 1][2])
            start_time = float(frame_data[key_frame_num - 1][1])
            end_time = float(frame_data[key_frame_num - 1][3])
        # frame_seg = frame_data[key_frame_num-1][0]+'-'+frame_data[key_frame_num-1][2]
        # video_name_and_frame = '_'.join([file.split('_')[0][4:], frame_seg])

            col.update({"video": video_number, "startFrame": start_frame}, {"$set": {"video": video_number, "startFrame": start_frame, "endFrame": end_frame, "startSecond": start_time, "endSecond": end_time}, "$addToSet": {"text": text}}, upsert = True)

            vid_num = file.split('_')[0][4:]

if __name__ == '__main__':
    tf.app.run()
