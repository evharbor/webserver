import os
import logging
# import concurrent_log_handler

# logging.handlers = concurrent_log_handler.ConcurrentRotatingFileHandler(filename='/var/log/harbor/ftp.log',
#                                                                             maxBytes=300,
#                                                                             backupCount=10,
#                                                                             use_gzip=True,)
# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,
#     'formatters': {
#         'default': {
#             'format': '%(remote_ip)s:%(remote_port)s-[%(username)s]'
#         },
#     },
#     'handlers': {
#         'file': {
#             'level': 'DEBUG',
#             'class': 'concurrent_log_handler.ConcurrentRotatingFileHandler',
#             'formatter': 'default',
#             'filename': '/var/log/harbor/ftp.log',
#             'maxBytes': 300,
#             'backupCount': 10,
#             'use_gzip': True,
#             'delay': True
#         }
#     },
#     'pyftpdlib': {
#         'handlers': ['file'],
#         'level': 'DEBUG',
#     },
# }
# logging.basicConfig.dictConfig(LOGGING)

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer, ThreadedFTPServer, MultiprocessFTPServer
from harbor_file_system import HarborFileSystem
from harbor_auth import HarborAuthorizer
from harbor_handler import HarborDTPHandler, HarborFTPHandler


def main():
    
    # Instantiate a dummy authorizer for managing 'virtual' users
    authorizer = HarborAuthorizer()
    # authorizer = DummyAuthorizer()

    #authorizer.add_user('root', 'root', '/home/ftp', perm='elradfmwM')
    # authorizer.add_anonymous('/root/ftp/')
 
    # Instantiate FTP handler class
    handler = HarborFTPHandler

    handler.abstracted_fs = HarborFileSystem
    handler.dtp_handler = HarborDTPHandler
    handler.authorizer = authorizer

    # log
    # logging.handlers = concurrent_log_handler.ConcurrentRotatingFileHandler(filename='/var/log/harbor/ftp.log',
    #                                                                         maxBytes=300,
    #                                                                         backupCount=10,
    #                                                                         use_gzip=True,)
    # logging.basicConfig(level=logging.INFO)
    logging.basicConfig(filename='/var/log/harbor/ftp.log', level=logging.INFO)
    # handler.log_prefix = '[%(time)s] %(remote_ip)s:%(remote_port)s-[%(username)s]'
    

    # Define a customized banner (string returned when client connects)
    handler.banner = "pyftpdlib based ftpd ready."
 
    # Specify a masquerade address and the range of ports to use for
    # passive connections.  Decomment in case you're behind a NAT.
    #handler.masquerade_address = '151.25.42.11'
    handler.passive_ports = range(2000, 3001)
 
    # Instantiate FTP server class and listen on 0.0.0.0:2121
    address = ('0.0.0.0', 21)
    # server = FTPServer(address, handler)
    # server = ThreadedFTPServer(address, handler)
    server = MultiprocessFTPServer(address, handler)
 
    # set a limit for connections
    server.max_cons = 1024
    server.max_cons_per_ip = 50
 
    # start ftp server
    server.serve_forever()
 
if __name__ == '__main__':
    main()
