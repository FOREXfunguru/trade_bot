'''
@date: 22/11/2020
@author: Ernesto Lowy
@email: ernestolowy@gmail.com
'''
from configparser import ConfigParser
import os
import pdb
import logging

logging.basicConfig(level=logging.INFO)

# create logger
c_logger = logging.getLogger(__name__)
c_logger.setLevel(logging.INFO)

c_logger.info("Reading config file")

DEFAULT_CONFIG_FILE = '../data/settings.ini'
def get_config_file():
    return os.environ.get('CONFIG_FILE', DEFAULT_CONFIG_FILE)

CONFIG_FILE = get_config_file()

c_logger.info("Reading config file with name: {0}".format(CONFIG_FILE))

def create_config(config_file=None):
    parser = ConfigParser()
    parser.read(config_file or CONFIG_FILE)
    return parser

CONFIG = create_config()
