'''
Created on Jun 13, 2018

@author: runshengsong
'''
import os
import glob

import keras

from keras.models import Model
from keras.optimizers import SGD
from keras.models import load_model
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.layers import Dense, GlobalAveragePooling2D
from keras.preprocessing.image import ImageDataGenerator

import settings

from app import app

TOPLESS_MODEL_PATH = app.config['VGG16_TOPLESS_MODEL_PATH']
PATH_TO_SAVE_MODELS = app.config['PATH_TO_SAVE_MODELS']

class Vgg16Retrainer:
    def __init__(self, model_name):
        self.model_name = model_name
        
    def retrain(self, local_data_path, nb_epoch, batch_size):
        """
        retrain the model
        """
        model_path = os.path.join(PATH_TO_SAVE_MODELS, model_name, model_name + '.h5')
        
        print "* Re-trainer: Loading Model {}...".format(self.model_name)
        # load the model
        this_model = load_model(model_path)
        
        # load the training data
        train_dir = os.path.join(local_data_path, "train")
        val_dir = os.path.join(local_data_path, "val")
        
        # set up parameters
        nb_train_samples = self.__get_nb_files(train_dir)
        nb_classes = len(glob.glob(train_dir + "/*"))
        nb_val_samples = self.__get_nb_files(val_dir)
        nb_epoch = int(nb_epoch)
        batch_size = int(batch_size)
        
        # data prep
        train_datagen =  ImageDataGenerator(
            preprocessing_function = preprocess_input
          )
        
        val_datagen = ImageDataGenerator(
            preprocessing_function=preprocess_input
            )
        
        # load training and validation data
        print "* Re-trainer: Loading Training and Validation Data..."
        train_generator = train_datagen.flow_from_directory(
            train_dir,
            target_size=(224, 224),
            batch_size=batch_size)
        
        validation_generator = val_datagen.flow_from_directory(
            val_dir,
            target_size=(224, 224),
            batch_size=batch_size,
            )
        
        # retrain the model
        this_model.fit_generator(train_generator,
                                 nb_epoch=nb_epoch,
                                 samples_per_epoch=nb_train_samples,
                                 validation_data=validation_generator,
                                 nb_val_samples=nb_val_samples,
                                 class_weight='auto')
        
        return this_model, model_path
          
class Vgg16TransferLeaner:
    def __init__(self, model_name):
        self.model_name = model_name
        
        # the creation of the model directory should be handled
        # in the API
        try:
            print "* Transfer: Loading Topless Model..."
            self.topless_model = load_model(TOPLESS_MODEL_PATH)
        except IOError:
            # load model from keras
            self.topless_model = VGG16(include_top=False, 
                                            weights='imagenet',
                                            input_shape=(224, 224, 3))
            
        self.new_model = None # init the new model

    def transfer_model(self, local_dir,
                       nb_epoch,
                       batch_size):
        """
        transfer the topless Vgg16 model
        to classify new classes
        """
        train_dir = os.path.join(local_dir, "train")
        val_dir = os.path.join(local_dir, "val")
        
        # set up parameters
        nb_train_samples = self.__get_nb_files(train_dir)
        nb_classes = len(glob.glob(train_dir + "/*"))
        nb_val_samples = self.__get_nb_files(val_dir)
        nb_epoch = int(nb_epoch)
        batch_size = int(batch_size)
        
        # data prep
        train_datagen =  ImageDataGenerator(
            preprocessing_function = preprocess_input
          )
        
        val_datagen = ImageDataGenerator(
            preprocessing_function=preprocess_input
            )
        
        # generator
        train_generator = train_datagen.flow_from_directory(
            train_dir,
            target_size=(224, 224),
            batch_size=batch_size)
        
        validation_generator = val_datagen.flow_from_directory(
            val_dir,
            target_size=(224, 224),
            batch_size=batch_size,
            )
        
        # get the class and label name, reverse key and value pair
        classes_label_dict = train_generator.class_indices
        classes_label_dict = {v: k for k, v in classes_label_dict.iteritems()}
        
        # add a new top layer base on the user data
        self.new_model = self.__add_new_last_layer(self.topless_model, nb_classes) 
        
        # set up transfer learning model
        self.__setup_to_transfer_learn(model=self.new_model, 
                                       base_model=self.topless_model)
        
        print "* Transfer: Added a New Last Layer... Starting Transfer Learning..."
        # train the new model for few epoch
        # TO DO:
        # celery tasks
        history_tl = self.new_model.fit_generator(train_generator,
                                         steps_per_epoch=nb_train_samples//batch_size,
                                         epochs=nb_epoch,
                                         validation_data=validation_generator,
                                         validation_steps=nb_val_samples//batch_size,
                                         class_weight='auto',
                                         verbose=1)
        
        # set up fine-tuning model
        self.__setup_to_finetune(self.new_model, nb_layer_to_freeze=10)
        
        print "* Transfer: Starting Fine-Tuning..."
        # train the new model again to fine-tune it
        history_ft = self.new_model.fit_generator(train_generator,
                                         steps_per_epoch=nb_train_samples//batch_size,
                                         epochs=nb_epoch,
                                         validation_data=validation_generator,
                                         validation_steps=nb_val_samples//batch_size,
                                         class_weight='auto',
                                         verbose=1)

        # return the model
        return self.new_model, classes_label_dict
        
    def __setup_to_finetune(self, model, nb_layer_to_freeze):
        """
        Freeze the bottom NB_IV3_LAYERS and retrain the remaining top layers.
        note: NB_IV3_LAYERS corresponds to the top 2 vgg blocks in the vgg16 arch
        Args:
        model: keras model
        """
        for layer in model.layers[:nb_layer_to_freeze]:
            layer.trainable = False
        for layer in model.layers[nb_layer_to_freeze:]:
            layer.trainable = True
        model.compile(optimizer=SGD(lr=0.0001, momentum=0.9), loss='categorical_crossentropy', metrics=['accuracy'])

    def __setup_to_transfer_learn(self, model, base_model):
        """Freeze all layers and compile the model"""
        for layer in base_model.layers:
            layer.trainable = False
        model.compile(optimizer='rmsprop', loss='categorical_crossentropy', metrics=['accuracy'])
        
    def __add_new_last_layer(self, topless_model, nb_classes):
        """
        add the last layer to the topless model
        """
        x = topless_model.output
        x = GlobalAveragePooling2D()(x)
        x = Dense(settings.FC_SIZE, activation='relu')(x) #new FC layer, random init
        predictions = Dense(nb_classes, activation='softmax')(x) #new softmax layer
        model = Model(input=topless_model.input, output=predictions)
        return model
        
    def __get_nb_files(self, directory):
        """Get number of files by searching local dir recursively"""
        if not os.path.exists(directory):
            return 0
        cnt = 0
        for r, dirs, files in os.walk(directory):
            for dr in dirs:
                cnt += len(glob.glob(os.path.join(r, dr + "/*")))
        return cnt