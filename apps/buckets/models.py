import uuid
from datetime import datetime, timedelta

from django.db import models
from django.contrib.auth import get_user_model
from mongoengine import DynamicDocument, OperationError
from mongoengine import fields,QuerySet


#获取用户模型
User = get_user_model()

# Create your models here.

def get_uuid1_hex_string():
    return uuid.uuid1().hex

class Bucket(models.Model):
    '''
    存储桶bucket类，bucket名称必须唯一（不包括软删除记录）
    '''
    PUBLIC = 1
    PRIVATE = 2
    ACCESS_PERMISSION_CHOICES = (
        (PUBLIC, '公有'),
        (PRIVATE, '私有'),
    )
    SOFT_DELETE_CHOICES = (
        (True, '删除'),
        (False, '正常'),
    )

    name = models.CharField(max_length=63, db_index=True, verbose_name='bucket名称')
    user = models.ForeignKey(to=User, on_delete=models.CASCADE, verbose_name='所属用户')
    created_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    collection_name = models.CharField(max_length=50, default=get_uuid1_hex_string, editable=False, verbose_name='存储桶对应的集合表名')
    access_permission = models.SmallIntegerField(choices=ACCESS_PERMISSION_CHOICES, default=PRIVATE, verbose_name='访问权限')
    soft_delete = models.BooleanField(choices=SOFT_DELETE_CHOICES, default=False, verbose_name='软删除') #True->删除状态
    modified_time = models.DateTimeField(auto_now=True, verbose_name='修改时间') # 修改时间可以指示删除时间
    objs_count = models.IntegerField(verbose_name='对象数量', default=0) # 桶内对象的数量
    size = models.BigIntegerField(verbose_name='桶大小', default=0) # 桶内对象的总大小

    class Meta:
        verbose_name = '存储桶'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name

    def __repr__(self):
        return f'<Bucket>{self.name}'

    @classmethod
    def get_user_valid_bucket_count(cls, user):
        '''获取用户有效的存储桶数量'''
        return cls.objects.filter(models.Q(user=user) & models.Q(soft_delete=False)).count()

    @classmethod
    def get_bucket_by_name(cls, bucket_name):
        '''
        获取存储通对象
        :param bucket_name: 存储通名称
        :return: Bucket对象; None(不存在)
        '''
        query_set = Bucket.objects.filter(models.Q(name=bucket_name) & models.Q(soft_delete=False))
        if query_set.exists():
            return query_set.first()

        return None

    def do_soft_delete(self):
        self.soft_delete = True
        self.save()

    def is_soft_deleted(self):
        return self.soft_delete

    def check_user_own_bucket(self, request):
        # bucket是否属于当前用户
        return request.user.id == self.user.id

    def get_bucket_mongo_collection_name(self):
        '''
        获得bucket对应的mongodb集合名
        :return: 集合名
        '''
        return f'bucket_{self.id}'

    def set_permission(self, public=False):
        '''
        设置存储桶公有或私有访问权限

        :param public: 公有(True)或私有(False)
        :return: True(success); False(error)
        '''
        if public == True and self.access_permission != self.PUBLIC:
            self.access_permission = self.PUBLIC
        elif  public == False and self.access_permission != self.PRIVATE:
            self.access_permission = self.PRIVATE
        else:
            return True

        try:
            self.save()
        except:
            return  False

        return True

    def is_public_permission(self):
        '''
        存储桶是否是公共访问权限

        :return: True(是公共); False(私有权限)
        '''
        if self.access_permission == self.PUBLIC:
            return True
        return False

    def obj_count_increase(self, save=True):
        '''
        存储桶对象数量加1

        :param save: 是否更新到数据库
        :return: True(success); False(failure)
        '''
        self.obj_count += 1
        if save:
            try:
                self.save()
            except:
                return False

        return True

    def obj_count_decrease(self, save=True):
        '''
        存储桶对象数量减1

        :param save: 是否更新到数据库
        :return: True(success); False(failure)
        '''
        self.obj_count = max(self.obj_count - 1, 0)
        if not save:
            try:
                self.save()
            except:
                return False

        return True


class BucketLimitConfig(models.Model):
    '''
    用户可拥有存储桶数量限制配置模型
    '''
    limit = models.IntegerField(verbose_name='可拥有存储桶上限', default=2)
    user = models.OneToOneField(to=User, related_name='bucketlimit', on_delete=models.CASCADE, verbose_name='用户')

    class Meta:
        verbose_name = '桶上限配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return str(self.limit)

    def __repr__(self):
        return f'limit<={self.limit}'

    @classmethod
    def get_user_bucket_limit(cls, user:User):
        obj, created = cls.objects.get_or_create(user=user)
        return obj.limit


class BucketFileInfoBase(DynamicDocument):
    '''
    存储桶bucket文件信息模型基类

    @ na : name，若该doc代表文件，则na为文件名，若该doc代表目录，则na为目录路径;
    @ fos: file_or_dir，用于判断该doc代表的是一个文件还是一个目录，若fod为True，则是文件，若fod为False，则是目录;
    @ did: 所在目录的objectID，若该doc代表文件，则did为该文件所属目录的id，若该doc代表目录，则did为该目录的上一级
                目录(父目录)的id;
    @ si : size,文件大小,字节数，若该doc代表文件，则si为该文件的大小，若该doc代表目录，则si为空；
    @ ult: upload_time，若该doc代表文件，则ult为该文件的上传时间，若该doc代表目录，则ult为该目录的创建时间
    @ upt: update_time，若该doc代表文件，则upt为该文件的最近修改时间，若该doc代表目录，则upt为空;
    @ sh : shared，若该doc代表文件，则sh用于判断文件是否允许共享，若sh为True，则文件可共享，若sh为False，则文件不能共享，
                且shp，stl，sst，set等字段为空；若该doc代表目录，则sh为空；
    @ shp: share_password，若该doc代表文件，且允许共享，则shp为该文件的共享密码，若该doc代表目录，则shp为空;
    @ stl: share_time_limit，若该doc代表文件，且允许共享，则stl用于判断该文件是否有共享时间限制，若stl为True，则文件有
                共享时间限制，若stl为False，则文件无共享时间限制，且sst，set等字段为空；若该doc代表目录，则stl为空;
    @ sst: share_start_time，允许共享且有时间限制，则sst为该文件的共享起始时间，若该doc代表目录，则sst为空;
    @ set: share_end_time，  允许共享且有时间限制，则set为该文件的共享终止时间，若该doc代表目录，则set为空;
    @ sds: soft delete status,软删除,True->删除状态，get_sds_display()可获取可读值
    '''
    SOFT_DELETE_STATUS_CHOICES = (
        (True, '删除'),
        (False, '正常'),
    )

    na = fields.StringField(required=True, unique=True) # name,文件名或目录名
    fod = fields.BooleanField(required=True) # file_or_dir; True==文件，False==目录
    did = fields.ObjectIdField() #父节点objectID
    si = fields.LongField() # 文件大小,字节数
    ult = fields.DateTimeField(default=datetime.utcnow) # 文件的上传时间，或目录的创建时间
    upt = fields.DateTimeField() # 文件的最近修改时间，目录，则upt为空
    dlc = fields.IntField() # 该文件的下载次数，目录时dlc为空
    bac = fields.ListField(fields.StringField()) # backup，该文件的备份地址，目录时为空
    arc = fields.ListField(fields.StringField()) # archive，该文件的归档地址，目录时arc为空
    sh = fields.BooleanField(default=False) # shared，若sh为True，则文件可共享，若sh为False，则文件不能共享
    shp = fields.StringField() # 该文件的共享密码，目录时为空
    stl = fields.BooleanField(default=True) # True: 文件有共享时间限制; False: 则文件无共享时间限制
    sst = fields.DateTimeField() # share_start_time, 该文件的共享起始时间
    set = fields.DateTimeField() # share_end_time,该文件的共享终止时间
    sds = fields.BooleanField(default=False, choices=SOFT_DELETE_STATUS_CHOICES) # soft delete status,软删除,True->删除状态

    meta = {
        'abstract': True,
        #db_alias用于指定当前模型默认绑定的mongodb连接，但可以用switch_db(Model, 'db2')临时改变对应的数据库连接
        'db_alias': 'default',
        'indexes': ['did', 'ult', ('fod', 'na')],  # 索引
        'ordering': ['fod', '-ult'], #文档降序，最近日期靠前
        # 'collection':'uploadfileinfo',#集合名字，默认为小写字母的类名
        # 'max_documents': 10000, #集合存储文档最大数量
        # 'max_size': 2000000, #集合的最大字节数
    }

    def do_soft_delete(self):
        '''
        软删除

        :return: True(success); False(error)
        '''
        self.sds = True
        self.upt = datetime.utcnow() # 修改时间标记删除时间

        try:
            self.save()
        except:
            return False
        return True

    def set_shared(self, sh=False, days=0):
        '''
        设置对象共享或私有权限

        :param sh: 共享(True)或私有(False)
        :param days: 共享天数，0表示永久共享, <0表示不共享
        :return: True(success); False(error)
        '''
        if sh == True:
            self.sh = True          # 共享
            now = datetime.utcnow()
            self.sst = now          # 共享时间
            if days == 0:
                self.stl = False    # 永久共享,没有共享时间限制
            elif days < 0:
                self.sh = False     # 私有
            else:
                self.stl = True     # 有共享时间限制
                self.set = now + timedelta(days=days) # 共享终止时间
        else:
            self.sh = False         # 私有

        try:
            self.save()
        except:
            return False
        return True

    def is_shared_and_in_shared_time(self):
        '''
        对象是否是分享的, 并且在有效分享时间内，即是否可公共访问
        :return: True(是), False(否)
        '''
        # 对象是否是分享的
        if not self.sh:
            return False

        # 是否有分享时间限制
        if not self.has_shared_limit():
            return True

        # 检查是否已过共享终止时间
        if self.is_shared_end_time_out():
            return False

        return True

    def has_shared_limit(self):
        '''
        是否有分享时间限制
        :return: True(有), False(无)
        '''
        return self.stl

    def is_shared_end_time_out(self):
        '''
        是否超过分享终止时间
        :return: True(超时)，False(未超时)
        '''
        td = datetime.utcnow() - self.set
        return td.total_seconds() > 0

    def download_cound_increase(self):
        '''
        下载次数加1

        :return: True(success); False(error)
        '''
        self.dlc = (self.dlc or 0) + 1  # 下载次数+1
        try:
            self.save()
        except:
            return False
        return True

    def is_file(self):
        return self.fod

    def do_delete(self):
        '''
        删除
        :return: True(删除成功); False(删除失败)
        '''
        try:
            self.delete()
        except OperationError:
            return False

        return True

    def get_obj_key(self, bucket_id):
        '''
        获取此文档在ceph中对应的对象id

        :param bucket_id:
        :return: type:str; 无效的参数返回None
        '''
        if isinstance(bucket_id, str) or isinstance(bucket_id, int):
            return str(bucket_id) + str(self.id)
        return None

    def do_save(self, **kwargs):
        '''
        创建一个文档或更新一个已存在的文档

        :return: True(成功); False(失败)
        '''
        try:
            self.save(**kwargs)
        except:
            return False

        return True
