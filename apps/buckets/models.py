from datetime import datetime

from django.db import models
from django.contrib.auth import get_user_model
from mongoengine import DynamicDocument, EmbeddedDocument
from mongoengine import fields
from mongoengine.base.datastructures import EmbeddedDocumentList


#获取用户模型
User = get_user_model()

# Create your models here.

class Bucket(models.Model):
	'''
	存储桶bucket类
	'''
	PUBLIC = 1
	PRIVATE = 2
	ACCESS_PERMISSION_CHOICES = (
		(PUBLIC, '私有'),
		(PRIVATE, '公有'),
	)

	name = models.CharField(max_length=50, db_index=True, unique=True, verbose_name='bucket名称')#bucket名称唯一
	user = models.ForeignKey(to=User, on_delete=models.CASCADE, verbose_name='所属用户')
	created_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
	collection_name = models.CharField(max_length=50, verbose_name='存储桶对应的集合表名')
	access_permission = models.SmallIntegerField(choices=ACCESS_PERMISSION_CHOICES, default=PRIVATE, verbose_name='访问权限')

	class Meta:
		verbose_name = '存储桶'
		verbose_name_plural = verbose_name



class FileChunkInfo(EmbeddedDocument):
	'''
	文件块信息模型
	'''
	bm = fields.IntField(required=True) # 文件块编号
	uuid = fields.StringField(required=True) # 文件快唯一标识
	md5 = fields.StringField(required=True, max_length=32, min_length=32) # 文件块MD5码
	up = fields.BooleanField(default=False) # 文件快是否已上传完成，True->已上传完成



class BucketFileInfo(DynamicDocument):
	'''
	存储桶bucket文件信息模型

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
	'''
	# UPLOADING = 1
	# COMPLETE = 2
	# STATUS_CHOICES = (
	# 	(UPLOADING, 'Incomplete'),
	# 	(COMPLETE, 'Complete'),
	# )

	na = fields.StringField(required=True) # name,文件名或目录名
	fod = fields.BooleanField(required=True) # file_or_dir; True==文件，False==目录
	did = fields.ObjectIdField() #父节点objectID字符串
	si = fields.LongField() # 文件大小,字节数
	ult = fields.DateTimeField(default=datetime.utcnow) # 文件的上传时间，或目录的创建时间
	upt = fields.DateTimeField() # 文件的最近修改时间，目录，则upt为空
	dlc = fields.IntField() # 该文件的下载次数，目录时dlc为空
	bac = fields.ListField(fields.StringField()) # backup，该文件的备份地址，目录时为空
	arc = fields.ListField(fields.StringField()) # archive，该文件的归档地址，目录时arc为空
	sh = fields.BooleanField() # shared，若sh为True，则文件可共享，若sh为False，则文件不能共享
	shp = fields.StringField() # 该文件的共享密码，目录时为空
	stl = fields.BooleanField() # True: 文件有共享时间限制; False: 则文件无共享时间限制
	sst = fields.DateTimeField() # share_start_time, 该文件的共享起始时间
	set = fields.DateTimeField() # share_end_time,该文件的共享终止时间

	# fcc = fields.IntField()  # file chunk count 文件的文件块数量，为空或0表示此文件未分块或者此记录为目录
	# fcil = fields.EmbeddedDocumentListField(FileChunkInfo) # FileChunkInfo列表，目录时fcil为空
	# fst = fields.IntField(choices=STATUS_CHOICES, default=UPLOADING) # file status,标记文件状态
	# fmd5 = fields.StringField(required=True, max_length=32, min_length=32)  # 文件MD5码

	meta = {
		#db_alias用于指定当前模型默认绑定的mongodb连接，但可以用switch_db(Model, 'db2')临时改变对应的数据库连接
		'db_alias': 'default',
		'indexes': ['did'],#索引
		'ordering': ['fod', '-ult'], #文档降序，最近日期靠前
		# 'collection':'uploadfileinfo',#集合名字，默认为小写字母的类名
		# 'max_documents': 10000, #集合存储文档最大数量
		# 'max_size': 2000000, #集合的最大字节数
	}

	# def get_fcil_manager(self):
	# 	return EmbeddedDocumentList(list_items=self.fcil, instance=self, name='fcil')




