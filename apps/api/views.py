from django.http import StreamingHttpResponse, FileResponse, Http404
from mongoengine.context_managers import switch_collection
from rest_framework import viewsets, status, generics, mixins
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser, BasePermission
from rest_framework.schemas import AutoSchema
from rest_framework.compat import coreapi, coreschema
from rest_framework.reverse import reverse

from buckets.utils import get_collection_name, BucketFileManagement
from utils.storagers import FileStorage, PathParser
from .models import User, Bucket, BucketFileInfo
from . import serializers
from utils.oss.rados_interfaces import CephRadosObject

# Create your views here.

class IsSuperUser(BasePermission):
    '''
    Allows access only to super users.
    '''
    def has_permission(self, request, view):
        return request.user and request.user.is_superuser


class CustomAutoSchema(AutoSchema):
    '''
    自定义Schema
    '''
    def get_manual_fields(self, path, method):
        '''
        重写方法，为每个方法自定义参数字段
        '''
        extra_fields = []
        if type(self._manual_fields) is dict and method in self._manual_fields:
            extra_fields = self._manual_fields[method]

        return extra_fields


class UserViewSet( mixins.RetrieveModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.ListModelMixin,
                   viewsets.GenericViewSet):
    '''
    用户类视图
    list:
    return user list.

    retrieve：
    return user infomation.

    create:
    create a user
    '''
    queryset = User.objects.all()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED, )

    def get_serializer_class(self):
        '''
        动态加载序列化器
        '''
        if self.action == 'create':
            return serializers.UserCreateSerializer

        return serializers.UserDeitalSerializer

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action in ['list', 'create', 'delete']:
            return [IsSuperUser()]
        return [IsSuperUser()]


class BucketViewSet(mixins.CreateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.ListModelMixin,
                   viewsets.GenericViewSet):
    '''
    存储桶视图

    list:
    return bucket list.

    retrieve:
    return bucket infomation.

    create:
    create a bucket

    delete:
    delete a bucket
    '''
    queryset = Bucket.objects.all()
    permission_classes = [IsAuthenticated]
    # serializer_class = serializers.BucketCreateSerializer

    def list(self, request, *args, **kwargs):
        if IsSuperUser().has_permission(request, view=None):
            pass # superuser return all
        else:
            self.queryset = Bucket.objects.filter(user=request.user).all() # user's own

        return super(BucketViewSet, self).list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['create', 'delete']:
            return serializers.BucketCreateSerializer

        return serializers.BucketSerializer

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action in ['list', 'create', 'delete']:
            return [IsAuthenticated()]
        return [permission() for permission in self.permission_classes]


class UploadFileViewSet(viewsets.GenericViewSet):
    '''
    上传文件视图集

    create:
    文件上传请求，服务器会生成一条文件对象记录，并返回文件对象的id：
    	Http Code: 状态码201：无异常时，返回数据：
    	{
            data: 客户端请求时，携带的数据,
            id: 文件id，上传文件块时url中需要,
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;

    update:
    文件块上传
        Http Code: 状态码201：上传成功无异常时，返回数据：
        {
            data: 客户端请求时，携带的参数,不包含数据块；
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;

    destroy:
    通过文件id,删除一个文件，或者取消上传一个文件
    '''
    queryset = {}
    permission_classes = [IsAuthenticated]
    # serializer_class = serializers.BucketCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.response_data, status=status.HTTP_201_CREATED)


    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action == 'update':
            return serializers.ChunkedUploadUpdateSerializer
        elif self.action == 'create':
            return serializers.ChunkedUploadCreateSerializer
        return serializers.ChunkedUploadUpdateSerializer

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        context = super(UploadFileViewSet, self).get_serializer_context()
        context['kwargs'] = self.kwargs
        return context


class DeleteFileViewSet(viewsets.GenericViewSet):
    '''
    删除或者取消上传文件视图集

    create:
    通过文件id,删除一个文件
    	Http Code: 状态码201：无异常时，返回数据：
    	{
            data: 客户端请求时，携带的数据,
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    serializer_class = serializers.FileDeleteSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.response_data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        pass


class DownloadFileViewSet(viewsets.GenericViewSet):
    '''
    分片下载文件数据块视图集

    create:
    通过文件id,自定义读取文件对象数据块；
    	Http Code: 状态码200：无异常时，返回bytes数据流，其他信息通过标头headers传递：
    	{
            evob_request_data: 客户端请求时，携带的数据,
            evob_chunk_size: 返回文件块大小
            evob_obj_size: 文件对象总大小
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;
        Http Code: 状态码404：找不到资源;
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    serializer_class = serializers.FileDownloadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        id = validated_data.get('id')
        chunk_offset = validated_data.get('chunk_offset')
        chunk_size = validated_data.get('chunk_size')
        collection_name = validated_data.get('_collection_name')

        with switch_collection(BucketFileInfo, collection_name):
            bfi = BucketFileInfo.objects(id=id).first()
            if not bfi:
                return Response({'id': '未找到id对应文件'}, status=status.HTTP_404_NOT_FOUND)

            # 读文件块
            # fstorage = FileStorage(str(bfi.id))
            # chunk = fstorage.read(chunk_size, offset=chunk_offset)
            rados = CephRadosObject(str(bfi.id))
            ok, chunk = rados.read(offset=chunk_offset, size=chunk_size)
            if not ok:
                response_data = {'data': serializer.data}
                response_data['error_text'] = 'server error,文件块读取失败'
                return Response(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 如果从0读文件就增加一次下载次数
            if chunk_offset == 0:
                bfi.dlc = (bfi.dlc or 0) + 1# 下载次数+1
                bfi.save()

        reponse = StreamingHttpResponse(chunk, content_type='application/octet-stream', status=status.HTTP_200_OK)
        reponse['evob_request_data'] = serializer.data
        reponse['evob_chunk_size'] = len(chunk)
        reponse['evob_obj_size'] = bfi.si
        return reponse


class DirectoryViewSet(viewsets.GenericViewSet):
    '''
    目录视图集

    list:
    获取一个目录下的文件信息；

    create:
    创建一个目录：
    	Http Code: 状态码200：无异常时，返回数据：
    	{
            data: 客户端请求时，携带的数据,
        }
        Http Code: 状态码400：参数有误时，返回数据：
        {
            error_text: 对应参数错误信息;
        }

    destroy:
    删除一个目录；
    Http Code: 状态码200;
        无异常时，返回数据：{'code': 200, 'code_text': '已成功删除'};
        异常时，返回数据：{'code': 404, 'code_text': '文件不存在'};
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'dir_path'
    lookup_value_regex = '.+'

    # api docs
    schema = CustomAutoSchema(
        manual_fields={
            'GET':[
                coreapi.Field(
                    name='bucket_name',
                    required=True,
                    location='query',
                    schema = coreschema.String(description='存储桶名称'),
                    ),
                coreapi.Field(
                    name='dir_path',
                    required=False,
                    location='query',
                    schema=coreschema.String(description='存储桶下目录路径')
                ),
            ],
            'DELETE': [
                coreapi.Field(
                    name='bucket_name',
                    required=True,
                    location='query',
                    schema=coreschema.String(description='存储桶名称'),
                ),
            ]
        }
    )

    def list(self, request, *args, **kwargs):
        bucket_name = request.query_params.get('bucket_name')
        dir_path = request.query_params.get('dir_path', '')

        if not Bucket.check_user_own_bucket(request, bucket_name):
            return Response({'code': 404, 'error_text': f'您不存在一个名称为“{bucket_name}”的存储桶'})

        bfm = BucketFileManagement(path=dir_path)
        with switch_collection(BucketFileInfo,
                               get_collection_name(bucket_name=bucket_name)):
            ok, files = bfm.get_cur_dir_files()
            if not ok:
                return Response({'code': 404, 'error_text': '参数有误，未找到相关记录'})

            queryset = files
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(queryset, many=True, context={'bucket_name': bucket_name, 'dir_path': dir_path})
            data = {
                'code': 200,
                'files': serializer.data,
                'bucket_name': bucket_name,
                'dir_path': dir_path,
                'ajax_upload_url': reverse('api:upload-list', kwargs={'version': 'v1'}),
            }
            return Response(data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if not serializer.is_valid(raise_exception=False):
            return Response({'code': 400, 'code_text': serializer.errors}, status=status.HTTP_200_OK)

        validated_data = serializer.validated_data
        bucket_name = validated_data.get('bucket_name', '')
        dir_path = validated_data.get('dir_path', '')
        dir_name = validated_data.get('dir_name', '')
        did = validated_data.get('did', None)

        with switch_collection(BucketFileInfo, get_collection_name(bucket_name)):
            bfinfo = BucketFileInfo(na=dir_path + '/' + dir_name if dir_path else dir_name,  # 目录名
                                    fod=False,  # 目录
                                    )
            # 有父节点
            if did:
                bfinfo.did = did
            bfinfo.save()

        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        dir_path = kwargs.get(self.lookup_field, '')
        bucket_name = request.query_params.get('bucket_name', '')

        pp = PathParser(path=dir_path)
        path, dir_name = pp.get_path_and_filename()
        if not bucket_name or not dir_name:
            return Response(data={'code': 400, 'code_text': 'bucket_name or dir_name不能为空'}, status=status.HTTP_400_BAD_REQUEST)

        obj = self.get_dir_object(bucket_name, path, dir_path)
        if not obj:
            data = {'code': 404, 'code_text': '文件不存在'}
        else:
            with switch_collection(BucketFileInfo, get_collection_name(bucket_name)):
                obj.do_soft_delete()
            data = {'code': 200, 'code_text': '已成功删除'}
        return Response(data=data, status=status.HTTP_200_OK)

    def get_serializer(self, *args, **kwargs):
        """
        Return the serializer instance that should be used for validating and
        deserializing input, and for serializing output.
        """
        serializer_class = self.get_serializer_class()
        context = self.get_serializer_context()
        context.update(kwargs.get('context', {}))
        kwargs['context'] = context
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['create', 'delete']:
            return serializers.DirectoryCreateSerializer
        return serializers.DirectoryListSerializer

    def get_dir_object(self, bucket_name, path, dir_name):
        """
        Returns the object the view is displaying.
        """
        bfm = BucketFileManagement(path=path)
        with switch_collection(BucketFileInfo, get_collection_name(bucket_name)):
            ok, obj = bfm.get_dir_exists(dir_name=dir_name)
            if not ok:
                return None
            return obj


class BucketFileViewSet(viewsets.GenericViewSet):
    '''
    存储桶文件视图集

    retrieve:
    通过文件绝对路径（以存储桶名开始）,下载文件对象；
    	Http Code: 状态码200：无异常时，返回bytes数据流；
        Http Code: 状态码400：文件路径参数有误：对应参数错误信息;
        Http Code: 状态码404：找不到资源;
        Http Code: 状态码500：服务器内部错误;

    destroy:
        通过文件绝对路径（以存储桶名开始）,下载文件对象；
    	Http Code: 状态码204：删除成功；
        Http Code: 状态码400：文件路径参数有误：对应参数错误信息;
        Http Code: 状态码404：找不到资源;
        Http Code: 状态码500：服务器内部错误;
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    serializer_class = serializers.FileDownloadSerializer
    lookup_field = 'filepath'
    lookup_value_regex = '.+'

    # api docs
    METHOD_FEILD = [
        coreapi.Field(
            name='version',
            required=True,
            location='path',
            schema=coreschema.String(description='API版本（v1, v2）')
        ),
        coreapi.Field(
            name='filepath',
            required=True,
            location='path',
            schema=coreschema.String(description='以存储桶名称开头的文件对象绝对路径，类型String'),
        ),
    ]
    schema = CustomAutoSchema(
        manual_fields = {
            'GET': METHOD_FEILD,
            'DELETE': METHOD_FEILD,
        }
    )

    def retrieve(self, request, *args, **kwargs):
        filepath = kwargs.get(self.lookup_field, '')
        bucket_name, path, filename = PathParser(filepath=filepath).get_bucket_path_and_filename()
        if not bucket_name or not filename:
            return Response(data={'code': 400, 'code_text': 'filepath参数有误'}, status=status.HTTP_400_BAD_REQUEST)
        fileobj = self.get_file_obj_or_404(bucket_name, path, filename)
        response = self.get_file_download_response(str(fileobj.id), filename)
        if not response:
            return Response(data={'code': 500, 'code_text': '服务器发生错误，获取文件返回对象错误'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return response

    def destroy(self, request, *args, **kwargs):
        filepath = kwargs.get(self.lookup_field, '')
        bucket_name, path, filename = PathParser(filepath=filepath).get_bucket_path_and_filename()
        if not bucket_name or not filename:
            return Response(data={'code': 400, 'code_text': 'filepath参数有误'}, status=status.HTTP_400_BAD_REQUEST)
        fileobj = self.get_file_obj_or_404(bucket_name, path, filename)
        with switch_collection(BucketFileInfo, get_collection_name(bucket_name=bucket_name)):
            fileobj.do_soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_file_obj_or_404(self, bucket_name, path, filename):
        """
        获取文件对象信息
        """
        bfm = BucketFileManagement(path=path)
        with switch_collection(BucketFileInfo, get_collection_name(bucket_name)):
            ok, obj = bfm.get_file_exists(file_name=filename)
            if not ok:
                return None
            if not obj:
                raise Http404
            return obj

    def get_file_download_response(self, file_id, filename):
        '''
        获取文件下载返回对象
        :param file_id: 文件Id, type: str
        :filename: 文件名， type: str
        :return:
            success：http返回对象，type: dict；
            error: None
        '''
        cro = CephRadosObject(file_id)
        file_generator = cro.read_obj_generator
        if not file_generator:
            return None

        response = FileResponse(file_generator())
        response['Content-Type'] = 'application/octet-stream'  # 注意格式
        response['Content-Disposition'] = f'attachment; filename="{filename}"; filename*=utf-8 ${filename}'  # 注意filename 这个是下载后的名字
        return response


