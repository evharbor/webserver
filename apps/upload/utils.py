import os
import uuid

from django.conf import settings
from django.http import Http404, StreamingHttpResponse, FileResponse
from mongoengine.context_managers import switch_collection, switch_db

from .models import UploadFileInfo, Bucket



class FileSystemHandlerBackend():
    '''
    基于文件系统的文件处理器后端
    '''

    ACTION_STORAGE = 1 #存储
    ACTION_DELETE = 2 #删除
    ACTION_DOWNLOAD = 3 #下载


    def __init__(self, request, action, bucket_name, uuid=None, *args, **kwargs):
        '''
        @ uuid:要操作的文件uuid,上传文件时参数uuid不需要传值
        @ action:操作类型
        '''
        #文件对应uuid
        self.uuid = uuid if uuid else self._get_new_uuid()
        #文件存储的目录
        self.base_dir = os.path.join(settings.MEDIA_ROOT, 'upload')
        self.request = request
        self._action = action #处理方式
        self._collection_name = self.request.user.username + '_' + bucket_name #每个存储桶对应的集合表名==用户名_存储桶名称


    def file_storage(self):
        '''
        存储文件
        :return: 成功：True，失败：False
        '''
        #获取上传的文件对象
        file_obj = self.request.FILES.get('file', None)
        if not file_obj:
            return False
        #路径不存在时创建路径
        base_dir = self.get_base_dir()
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        #保存文件
        full_path_filename = self.get_full_path_filename()
        with open(full_path_filename, 'wb') as f:
            for chunk in file_obj.chunks():
                f.write(chunk)

        #保存对应文件记录到指定集合
        with switch_collection(UploadFileInfo, self._collection_name) as FileInfo:
            UploadFileInfo(uuid=self.uuid, filename=file_obj.name, size=file_obj.size).save()

        return True



    def file_detele(self):
        '''删除文件'''
        #是否存在uuid对应文件
        ok, finfo = self.get_file_info()
        if not ok:
            return False

        full_path_filename = self.get_full_path_filename()
        #删除文件和文件记录
        try:
            os.remove(full_path_filename)
        except FileNotFoundError:
            pass

        #切换到对应集合
        with switch_collection(UploadFileInfo, self.get_collection_name()):
            finfo.delete()

        return True


    def file_download(self):
        #是否存在uuid对应文件
        ok, finfo = self.get_file_info()
        if not ok:
            return False

        #文件是否存在
        full_path_filename = self.get_full_path_filename()
        if not self.is_file_exists(full_path_filename):
            return False

        # response = StreamingHttpResponse(file_read_iterator(full_path_filename)) 
        response = FileResponse(self.file_read_iterator(full_path_filename))
        response['Content-Type'] = 'application/octet-stream'  # 注意格式
        response['Content-Disposition'] = f'attachment;filename="{finfo.filename}"'  # 注意filename 这个是下载后的名字
        return response

            
    def file_read_iterator(self, file_name, chunk_size=1024*2):
        '''
        读取文件生成器
        '''
        with open(file_name, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if chunk:
                    yield chunk
                else:
                    break

    def do_action(self, action=None):
        '''上传/下载/删除操作执行者'''
        act = action if action else self._action
        if act == self.ACTION_STORAGE:
            return self.file_storage()
        elif act == self.ACTION_DOWNLOAD:
            return self.file_download()
        elif act == self.ACTION_DELETE:
            return self.file_detele()


    def _get_new_uuid(self):
        '''创建一个新的uuid字符串'''
        uid = uuid.uuid1()
        return str(uid)

    def get_base_dir(self):
        '''获得文件存储的目录'''
        return self.base_dir

    def get_full_path_filename(self):
        '''文件绝对路径'''
        return os.path.join(self.base_dir, self.uuid) 

    def get_file_info(self):
        '''是否存在uuid对应文件记录'''
        # 切换到指定集合查询对应文件记录
        with switch_collection(UploadFileInfo, self.get_collection_name()):
            finfos = UploadFileInfo.objects(uuid=self.uuid)
            if finfos:
                finfo = finfos.first()
                return True, finfo
        return False, None

    def is_file_exists(self, full_path_filename=None):
        '''检查文件是否存在'''
        filename = full_path_filename if full_path_filename else self.get_full_path_filename()
        return os.path.exists(filename)

    def get_collection_name(self):
        '''获得当前用户存储桶Bucket对应集合名称'''
        return self._collection_name




def get_collection_name(username, bucket_name):
    '''获得当前用户存储桶Bucket对应集合名称'''
    return f'{username}_{bucket_name}'