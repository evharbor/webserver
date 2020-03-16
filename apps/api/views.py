from collections import OrderedDict
import logging
import os
import binascii
from io import BytesIO

from django.http import StreamingHttpResponse, FileResponse, QueryDict
from django.utils.http import urlquote
from django.core.validators import validate_email
from django.core import exceptions
from django.urls import reverse as django_reverse
from rest_framework import status, mixins
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import Serializer, ValidationError
from rest_framework.authtoken.models import Token
from rest_framework import parsers
from rest_framework.decorators import action
from drf_yasg.utils import swagger_auto_schema, no_body
from drf_yasg import openapi

from buckets.utils import (BucketFileManagement, create_table_for_model_class, delete_table_for_model_class)
from users.views import send_active_url_email
from users.models import AuthKey
from users.auth.serializers import AuthKeyDumpSerializer
from utils.storagers import PathParser
from utils.oss import HarborObject, RadosError
from utils.log.decorators import log_used_time
from utils.jwt_token import JWTokenTool2
from utils.view import CustomGenericViewSet
from utils.time import to_django_timezone
from vpn.models import VPNAuth
from .models import User, Bucket
from . import serializers
from . import paginations
from . import permissions
from . import throttles
from .harbor import HarborError, HarborManager

# Create your views here.
logger = logging.getLogger('django.request')#这里的日志记录器要和setting中的loggers选项对应，不能随意给参
debug_logger = logging.getLogger('debug')#这里的日志记录器要和setting中的loggers选项对应，不能随意给参


def rand_hex_string(len=10):
    return binascii.hexlify(os.urandom(len//2)).decode()


def rand_share_code():
    return rand_hex_string(4)


def serializer_error_text(errors, default: str = ''):
    """
    序列化器验证错误信息

    :param errors: serializer.errors, type: ReturnDict()
    :param default: 获取信息失败时默认返回信息
    """
    msg = default if default else '参数有误，验证未通过'
    try:
        for key in errors:
            val = errors[key]
            msg = f'{key}, {val[0]}'
            break
    except Exception as e:
        pass

    return msg


def get_user_own_bucket(bucket_name, request):
    '''
    获取当前用户的存储桶

    :param bucket_name: 存储通名称
    :param request: 请求对象
    :return:
        success: bucket
        failure: None
    '''
    bucket = Bucket.get_bucket_by_name(bucket_name)
    if not bucket:
        return None
    if not bucket.check_user_own_bucket(request.user):
        return None
    return bucket


def str_to_int_or_default(val, default):
    '''
    字符串转int，转换失败返回设置的默认值

    :param val: 待转化的字符串
    :param default: 转换失败返回的值
    :return:
        int     # success
        default # failed
    '''
    try:
        return int(val)
    except Exception:
        return default


class UserViewSet(mixins.ListModelMixin,
                  CustomGenericViewSet):
    '''
    用户类视图
    list:
        获取用户列表

        获取用户列表,需要超级用户权限

        >> http code 200 返回内容:
            {
              "count": 2,  # 总数
              "next": null, # 下一页url
              "previous": null, # 上一页url
              "results": [
                {
                  "id": 3,
                  "username": "xx@xx.com",
                  "email": "xx@xx.com",
                  "date_joined": "2018-12-03T17:03:00+08:00",
                  "last_login": "2019-03-15T09:36:49+08:00",
                  "first_name": "",
                  "last_name": "",
                  "is_active": true,
                  "telephone": "",
                  "company": ""
                },
                {
                  ...
                }
              ]
            }

    retrieve:
    获取一个用户详细信息

        需要超级用户权限，或当前用户信息

        http code 200 返回内容:
            {
              "id": 3,
              "username": "xx@xx.com",
              "email": "xx@xx.com",
              "date_joined": "2018-12-03T17:03:00+08:00",
              "last_login": "2019-03-15T09:36:49+08:00",
              "first_name": "",
              "last_name": "",
              "is_active": true,
              "telephone": "",
              "company": ""
            }
        http code 403 返回内容:
            {
                "detail": "您没有执行该操作的权限。"
            }

    create:
    注册一个用户

        http code 201 返回内容:
            {
                'code': 201,
                'code_text': '用户注册成功，请登录邮箱访问收到的连接以激活用户',
                'data': { }  # 请求提交的数据
            }
        http code 500:
            {
                'detail': '激活链接邮件发送失败'
            }

    destroy:
    删除一个用户，需要超级管理员权限

        http code 204 无返回内容

    partial_update:
    修改用户信息

    1、超级职员用户拥有所有权限；
    2、用户拥有修改自己信息的权限；
    3、超级用户只有修改普通用户信息的权限

        http code 200 返回内容:
            {
                'code': 200,
                'code_text': '修改成功',
                'data':{ }   # 请求时提交的数据
            }
        http code 403:
            {
                'detail': 'xxx'
            }
    '''
    queryset = User.objects.all()
    lookup_field = 'username'
    lookup_value_regex = '.+'

    @swagger_auto_schema(
        operation_summary='注册一个用户',
        responses={
            status.HTTP_200_OK: ''
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        if not send_active_url_email(request._request, user.email, user):
            return Response({'detail': '激活链接邮件发送失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        data = {
            'code': 201,
            'code_text': '用户注册成功，请登录邮箱访问收到的连接以激活用户',
            'data': serializer.validated_data,
        }
        return Response(data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if not (request.user.id == instance.id):
            return Response(data={"detail": "您没有执行该操作的权限。"}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self.has_update_user_permission(request, instance=instance):
            return Response(data={'detail': 'You do not have permission to change this user information'},
                            status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response({'code': 200, 'code_text': '修改成功', 'data':serializer.validated_data})

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.is_active != False:
            user.is_active = False
            user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def has_update_user_permission(self, request, instance):
        '''
        当前用户是否有修改给定用户信息的权限
        1、超级职员用户拥有所有权限；
        2、用户拥有修改自己信息的权限；
        3、超级用户只有修改普通用户信息的权限；

        :param request:
        :param instance: 用户实例
        :return:
            True: has permission
            False: has not permission
        '''
        user = request.user
        if not user.id: # 未认证用户
            return False

        # 当前用户是超级职员用户，有超级权限
        if user.is_superuser and user.is_staff:
            return True

        # 当前用户不是APP超级用户，只有修改自己信息的权限
        if not user.is_app_superuser():
            # 当前用户修改自己的信息
            if user.id == instance.id:
                return True

            return False

        # 当前APP超级用户，只有修改普通用户的权限
        elif not instance.is_superuser:
            return True

        return False


    def get_serializer_class(self):
        '''
        动态加载序列化器
        '''
        if self.action == 'create':
            return serializers.UserCreateSerializer
        elif self.action == 'partial_update':
            return serializers.UserUpdateSerializer

        return serializers.UserDeitalSerializer

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action =='list':
            return [permissions.IsSuperUser()]
        elif self.action == 'create':
            return []
        elif self.action in ['retrieve', 'update', 'partial_update']:
            return [IsAuthenticated()]
        elif self.action == 'delete':
            return [permissions.IsSuperAndStaffUser()]
        return [permissions.IsSuperUser()]


class BucketViewSet(CustomGenericViewSet):
    '''
    存储桶视图

    create:
    创建一个新的存储桶
    存储桶名称，名称唯一，不可使用已存在的名称，符合DNS标准的存储桶名称，英文字母、数字和-组成，3-63个字符

        >>Http Code: 状态码201；创建成功时：
            {
              "code": 201,
              "code_text": "创建成功",
              "data": {                 //请求时提交数据
                "name": "333"
              },
              "bucket": {               //bucket对象信息
                "id": 225,
                "name": "333",
                "user": {
                  "id": 3,
                  "username": "869588058@qq.com"
                },
                "created_time": "2019-02-20T13:56:25+08:00",
                "access_permission": "私有",
                "ftp_enable": false,
                "ftp_password": "696674124f",
                "ftp_ro_password": "9563d3cc29"
              }
            }
        >>Http Code: 状态码400,参数有误：
            {
                'code': 400,
                'code_text': 'xxx',      //错误码表述信息
                'data': serializer.data, //请求时提交数据
                'existing': true or  false  // true表示资源已存在
            }

    delete:
    删除一个存储桶

        >>Http Code: 状态码204,存储桶删除成功
        >>Http Code: 状态码400
            {
                'code': 400,
                'code_text': '存储桶id有误'
            }
        >>Http Code: 状态码404：
            {
                'code': 404,
                'code_text': 'xxxxx'
            }

    partial_update:
    存储桶访问权限设置

        Http Code: 状态码200：上传成功无异常时，返回数据：
        {
            'code': 200,
            'code_text': '对象共享设置成功'，
            'public': xxx,
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;
        Http Code: 状态码404;

        Http code: 状态码500：
        {
            "code": 500,
            "code_text": "保存到数据库时错误"
        }

    '''
    queryset = Bucket.objects.select_related('user').all()
    permission_classes = [IsAuthenticated]
    pagination_class = paginations.BucketsLimitOffsetPagination
    lookup_field = 'id_or_name'
    lookup_value_regex = '[a-z0-9-]+'

    DETAIL_BASE_PARAMS = [
        openapi.Parameter(
            name='id_or_name',
            in_=openapi.IN_PATH,
            type=openapi.TYPE_STRING,
            required=True,
            description='默认为bucket ID，使用bucket name需要通过参数by-name指示'
        ),
        openapi.Parameter(
            name='by-name',
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_BOOLEAN,
            required=False,
            description='true,表示使用bucket name指定bucket；其他值忽略'
        )
    ]

    @swagger_auto_schema(
        operation_summary='获取存储桶列表',
        responses={
            status.HTTP_200_OK: """
                {
                  "count": 18,
                  "next": null,
                  "page": {
                    "current": 1,
                    "final": 1
                  },
                  "previous": null,
                  "buckets": [
                    {
                      "id": 222,
                      "name": "hhf",
                      "user": {
                        "id": 3,
                        "username": "869588058@qq.com"
                      },
                      "created_time": "2019-02-20T13:56:25+08:00",
                      "access_permission": "公有",
                      "ftp_enable": false,
                      "ftp_password": "1a0cdf3283",
                      "ftp_ro_password": "666666666"
                    },
                  ]
                }
            """
        }
    )
    def list(self, request, *args, **kwargs):
        '''
        获取存储桶列表
        '''
        self.queryset = Bucket.objects.select_related('user').filter(user=request.user).all() # user's own

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            data = {'code': 200, 'buckets': serializer.data,}
        return Response(data)

    @swagger_auto_schema(
        operation_summary='创建一个存储桶',
        responses={
            status.HTTP_201_CREATED: 'OK'
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid(raise_exception=False):
            code_text = '参数验证有误'
            existing = False
            try:
                for key, err_list in serializer.errors.items():
                    for err in err_list:
                        code_text = err
                        if err.code == 'existing':
                            existing = True
            except:
                pass

            data = {
                'code': 400,
                'code_text': code_text,
                'existing': existing,
                'data': serializer.data,
            }

            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        # 创建bucket,创建bucket的shard集合
        try:
            bucket = serializer.save()
        except Exception as e:
            return Response(data={'code': 500, 'code_text': f'创建桶失败，{str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        col_name = bucket.get_bucket_table_name()
        bfm = BucketFileManagement(collection_name=col_name)
        model_class = bfm.get_obj_model_class()
        if not create_table_for_model_class(model=model_class):
            if not create_table_for_model_class(model=model_class):
                bucket.delete()
                delete_table_for_model_class(model=model_class)
                logger.error(f'创建桶“{bucket.name}”的数据库表失败')
                return Response(data={'code': 500, 'code_text': '创建桶失败，数据库错误'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        data = {
            'code': 201,
            'code_text': '创建成功',
            'data': serializer.data,
            'bucket': serializers.BucketSerializer(serializer.instance).data
        }
        return Response(data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary='通过桶ID或name获取一个存储桶详细信息',
        manual_parameters=DETAIL_BASE_PARAMS,
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "bucket": {
                    "id": 222,
                    "name": "hhf",
                    "user": {
                      "id": 3,
                      "username": "869588058@qq.com"
                    },
                    "created_time": "2019-02-20T13:56:25+08:00",
                    "access_permission": "公有",
                    "ftp_enable": false,
                    "ftp_password": "1a0cdf3283",
                    "ftp_ro_password": "666666666"
                  }
                }
            """
        }
    )
    def retrieve(self, request, *args, **kwargs):
        '''
        获取一个存储桶详细信息
        '''
        ok, ret = self.get_user_bucket(request=request, kwargs=kwargs)
        if not ok:
            return ret

        serializer = self.get_serializer(ret)
        return Response({'code': 200, 'bucket': serializer.data})

    @swagger_auto_schema(
        operation_summary='删除一个存储桶',
        manual_parameters=DETAIL_BASE_PARAMS + [
            openapi.Parameter(
                name='ids', in_=openapi.IN_QUERY,
                type=openapi.TYPE_ARRAY,
                items=openapi.Items(type=openapi.TYPE_INTEGER),
                description="存储桶id列表或数组，删除多个存储桶时，通过此参数传递其他存储桶id",
                required=False
            ),
        ],
        responses={
            status.HTTP_204_NO_CONTENT: 'NO_CONTENT'
        }
    )
    def destroy(self, request, *args, **kwargs):
        try:
            ids = self.get_buckets_ids(request)
        except ValueError as e:
            return Response(data={'code': 400, 'code_text': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        ok, ret = self.get_user_bucket(request=request, kwargs=kwargs)
        if not ok:
            return ret
        bucket = ret
        if not bucket.delete_and_archive():  # 删除归档
            return Response(data={'code': 500, 'code_text': '删除存储桶失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if ids:
            buckets = Bucket.objects.select_related('user').filter(id__in=ids).filter(user=request.user).all()
            if not buckets.exists():
                return Response(data={'code': 404, 'code_text': '未找到要删除的存储桶'}, status=status.HTTP_404_NOT_FOUND)
            for bucket in buckets:
                if not bucket.delete_and_archive():  # 删除归档
                    return Response(data={'code': 500, 'code_text': '删除存储桶失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @swagger_auto_schema(
        operation_summary='存储桶访问权限设置',
        request_body=no_body,
        manual_parameters=DETAIL_BASE_PARAMS + [
            openapi.Parameter(
                name='public', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="设置访问权限, 1(公有)，2(私有)，3（公有可读可写）",
                required=True
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "code_text": "存储桶权限设置成功",
                  "public": 1,
                  "share": [
                    "http://159.226.91.140:8000/share/s/hhf"
                  ]
                }
            """
        }
    )
    def partial_update(self, request, *args, **kwargs):
        public = str_to_int_or_default(request.query_params.get('public', ''), 0)
        if public not in [1, 2, 3]:
            return Response(data={'code': 400, 'code_text': 'public参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        ok, ret = self.get_user_bucket(request=request, kwargs=kwargs)
        if not ok:
            return ret

        bucket = ret
        share_urls = []
        url = django_reverse('share:share-view', kwargs={'share_base': bucket.name})
        url = request.build_absolute_uri(url)
        share_urls.append(url)
        if not bucket.set_permission(public=public):
            return Response(data={'code': 500, 'code_text': '更新数据库数据时错误'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        data = {
            'code': 200,
            'code_text': '存储桶权限设置成功',
            'public': public,
            'share': share_urls
        }
        return Response(data=data, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        operation_summary='存储桶备注信息设置',
        request_body=no_body,
        manual_parameters=DETAIL_BASE_PARAMS + [
            openapi.Parameter(
                name='remarks', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="备注信息",
                required=True
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                    {
                      "code": 200,
                      "code_text": "存储桶备注信息设置成功",
                    }
                """
        }
    )
    @action(methods=['patch'], detail=True, url_path='remark', url_name='remark')
    def remarks(self, request, *args, **kwargs):
        """
        存储桶备注信息设置
        """
        remarks = request.query_params.get('remarks', '')
        if not remarks:
            return Response(data={'code': 400, 'code_text': '备注信息不能为空'}, status=status.HTTP_400_BAD_REQUEST)

        ok, ret = self.get_user_bucket(request=request, kwargs=kwargs)
        if not ok:
            return ret
        bucket = ret

        if not bucket.set_remarks(remarks=remarks):
            return Response(data={'code': 500, 'code_text': '设置备注信息失败，更新数据库数据时错误'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        data = {
            'code': 200,
            'code_text': '存储桶备注信息设置成功',
        }
        return Response(data=data, status=status.HTTP_200_OK)

    def get_user_bucket(self, request, kwargs):
        """
        :return:
            (True, Bucket())
            (False, Response())
        """
        id_or_name = kwargs.get(self.lookup_field, '')
        by_name = request.query_params.get('by-name', '').lower()
        if by_name == 'true':
            bucket = Bucket.objects.select_related('user').filter(name=id_or_name).first()
        else:
            try:
                bid = int(id_or_name)
            except Exception as e:
                return False, Response({'code': 400, 'code_text': '无效的存储桶ID'}, status=status.HTTP_400_BAD_REQUEST)
            bucket = Bucket.objects.filter(id=bid).first()

        if not bucket:
            return False, Response({'code': 404, 'code_text': '存储桶不存在'})

        if not bucket.check_user_own_bucket(request.user):
            return False, Response({'code': 403, 'code_text': '您没有操作此存储桶的权限'}, status=status.HTTP_403_FORBIDDEN)
        return True, bucket

    def get_buckets_ids(self, request, **kwargs):
        '''
        获取存储桶id列表
        :param request:
        :return:
            ids: list
        :raises: ValueError
        '''
        if isinstance(request.query_params, QueryDict):
            ids = request.query_params.getlist('ids')
        else:
            ids = request.query_params.get('ids')

        if not isinstance(ids, list):
            return []

        try:
            ids = [int(i) for i in ids]
        except ValueError:
            return ValueError('存储桶id有误')

        return ids

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['list', 'retrieve']:
            return serializers.BucketSerializer
        elif self.action =='create':
            return serializers.BucketCreateSerializer
        return Serializer

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action in ['list', 'create', 'delete']:
            return [IsAuthenticated()]
        return [permission() for permission in self.permission_classes]


class ObjViewSet(CustomGenericViewSet):
    '''
    文件对象视图集

    create_detail:
        通过文件对象绝对路径分片上传文件对象

        说明：
        * 请求类型ContentType = multipart/form-data；不是json，请求体中分片chunk当成是一个文件或类文件处理；
        * 小文件可以作为一个分片上传，大文件请自行分片上传，分片过大可能上传失败，建议分片大小5-10MB；对象上传支持部分上传，
          分片上传数据直接写入对象，已成功上传的分片数据永久有效且不可撤销，请自行记录上传过程以实现断点续传；
        * 文件对象已存在时，数据上传会覆盖原数据，文件对象不存在，会自动创建文件对象，并且文件对象的大小只增不减；
          如果覆盖（已存在同名的对象）上传了一个新文件，新文件的大小小于原同名对象，上传完成后的对象大小仍然保持
          原对象大小（即对象大小只增不减），如果这不符合你的需求，参考以下2种方法：
          (1)先尝试删除对象（对象不存在返回404，成功删除返回204），再上传；
          (2)访问API时，提交reset参数，reset=true时，再保存分片数据前会先调整对象大小（如果对象已存在），未提供reset参
            数或参数为其他值，忽略之。
          ## 特别提醒：切记在需要时只在上传第一个分片时提交reset参数，否者在上传其他分片提交此参数会调整对象大小，
          已上传的分片数据会丢失。

        注意：
        分片上传现不支持并发上传，并发上传可能造成脏数据，上传分片顺序没有要求，请一个分片上传成功后再上传另一个分片

        Http Code: 状态码200：上传成功无异常时，返回数据：
        {
          "chunk_offset": 0,    # 请求参数
          "chunk": null,
          "chunk_size": 34,     # 请求参数
          "created": true       # 上传第一个分片时，可用于判断对象是否是新建的，True(新建的)
        }
        Http Code: 状态码400：参数有误时，返回数据：
            {
                'code': 400,
                'code_text': '对应参数错误信息'
            }
        Http Code: 状态码500
            {
                'code': 500,
                'code_text': '文件块rados写入失败'
            }

    retrieve:
        通过文件对象绝对路径,下载文件对象，或者自定义读取对象数据块

        *注：
        1. offset && size(最大20MB，否则400错误) 参数校验失败时返回状态码400和对应参数错误信息，无误时，返回bytes数据流
        2. 不带参数时，返回整个文件对象；

    	>>Http Code: 状态码200：
             evhb_obj_size,文件对象总大小信息,通过标头headers传递：自定义读取时：返回指定大小的bytes数据流；
            其他,返回整个文件对象bytes数据流

        >>Http Code: 状态码400：文件路径参数有误：对应参数错误信息;
            {
                'code': 400,
                'code_text': 'xxxx参数有误'
            }
        >>Http Code: 状态码404：找不到资源;
        >>Http Code: 状态码500：服务器内部错误;

    destroy:
        删除对象

        通过文件对象绝对路径,删除文件对象；

        >>Http Code: 状态码204：删除成功，NO_CONTENT；
        >>Http Code: 状态码400：文件路径参数有误：对应参数错误信息;
            {
                'code': 400,
                'code_text': '参数有误'
            }
        >>Http Code: 状态码404：找不到资源;
        >>Http Code: 状态码500：服务器内部错误;

    partial_update:
    对象共享或私有权限设置

        Http Code: 状态码200：上传成功无异常时，返回数据：
        {
            'code': 200,
            'code_text': '对象共享设置成功'，
            "share_uri": "xxx"    # 分享下载uri
            'share': xxx,
            'days': xxx
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;
        Http Code: 状态码404;

    '''
    queryset = {}
    # permission_classes = [IsAuthenticated]
    lookup_field = 'objpath'
    lookup_value_regex = '.+'
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)


    @swagger_auto_schema(
        operation_summary='分片上传文件对象',
        manual_parameters=[
            openapi.Parameter(
                name='objpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="文件对象绝对路径",
                required=True
            ),
            openapi.Parameter(
                name='reset', in_=openapi.IN_QUERY,
                type=openapi.TYPE_BOOLEAN,
                description="reset=true时，如果对象已存在，重置对象大小为0",
                required=False
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                {
                  "chunk_offset": 0,
                  "chunk": null,
                  "chunk_size": 34,
                  "created": true
                }
            """
        }
    )
    def create_detail(self, request, *args, **kwargs):
        objpath = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name', '')
        reset = request.query_params.get('reset', '').lower()
        if reset == 'true':
            reset = True
        else:
            reset = False

        # 数据验证
        try:
            put_data = self.get_data(request)
        except Exception as e:
            logger.error(f'in request.data during upload file: {e}')
            return Response({
                'code': 500, 'code_text': 'SERVER ERROR',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = self.get_serializer(data=put_data)
        if not serializer.is_valid(raise_exception=False):
            msg = serializer_error_text(serializer.errors)
            return Response({'code': 400, 'code_text': msg}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.data
        offset = data.get('chunk_offset')
        file = request.data.get('chunk')

        hManager = HarborManager()
        try:
            created = hManager.write_file(bucket_name=bucket_name, obj_path=objpath, offset=offset, file=file,
                                           reset=reset, user=request.user)
        except HarborError as e:
            return Response(data={'code':e.code, 'code_text': e.msg}, status=e.code)

        data['created'] = created
        return Response(data, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        operation_summary='下载文件对象，自定义读取对象数据块',
        manual_parameters=[
            openapi.Parameter(
                name='offset', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="要读取的文件块在整个文件中的起始位置（bytes偏移量)",
                required=False
            ),
            openapi.Parameter(
                name='size', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="要读取的文件块的字节大小",
                required=False
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                Content-Type: application/octet-stream
            """
        }
    )
    def retrieve(self, request, *args, **kwargs):

        objpath = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name','')

        validated_param, valid_response = self.custom_read_param_validate_or_response(request)
        if not validated_param and valid_response:
            return valid_response

        # 自定义读取文件对象
        if validated_param:
            offset = validated_param.get('offset')
            size = validated_param.get('size')
            hManager = HarborManager()
            try:
                chunk, obj = hManager.read_chunk(bucket_name=bucket_name, obj_path=objpath,
                                                      offset=offset, size=size, user = request.user)
            except HarborError as e:
                return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

            return self.wrap_chunk_response(chunk=chunk, obj_size=obj.si)

        # 下载整个文件对象
        hManager = HarborManager()
        try:
            file_generator, obj = hManager.get_obj_generator(bucket_name=bucket_name, obj_path=objpath,
                                                                  user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        filename = obj.name
        filename = urlquote(filename)  # 中文文件名需要
        response = FileResponse(file_generator)
        response['Content-Type'] = 'application/octet-stream'  # 注意格式
        response['Content-Length'] = obj.si
        response['Content-Disposition'] = f"attachment;filename*=utf-8''{filename}"  # 注意filename 这个是下载后的名字
        response['evob_obj_size'] = obj.si
        return response

    def destroy(self, request, *args, **kwargs):
        objpath = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name','')
        hManager = HarborManager()
        try:
            ok = hManager.delete_object(bucket_name=bucket_name, obj_path=objpath, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        if not ok:
            return Response(data={'code': 500, 'code_text': '删除失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @swagger_auto_schema(
        operation_summary='对象共享或私有权限设置',
        manual_parameters=[
            openapi.Parameter(
                name='share', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="分享访问权限，0（不分享禁止访问），1（分享只读），2（分享可读可写）",
                required=True
            ),
            openapi.Parameter(
                name='days', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="对象公开分享天数(share!=0时有效)，0表示永久公开，负数表示不公开，默认为0",
                required=False
            ),
            openapi.Parameter(
                name='password', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="分享密码，此参数不存在，不设密码；可指定4-8字符；若为空，随机分配密码",
                required=False
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "code_text": "对象共享权限设置成功",
                  "share": 1,
                  "days": 2,
                  "share_uri": "xxx"    # 分享下载uri
                }        
            """
        }
    )
    def partial_update(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        objpath = kwargs.get(self.lookup_field, '')
        pw = request.query_params.get('password', None)

        if pw:  # 指定密码
            if not (4 <= len(pw) <= 8):
                return Response(data={'code': 400, 'code_text': 'password参数长度为4-8个字符'}, status=status.HTTP_400_BAD_REQUEST)
            password = pw
        elif pw is None:  # 不设密码
            password = ''
        else:  # 随机分配密码
            password = rand_share_code()

        days = str_to_int_or_default(request.query_params.get('days', 0), None)
        if days is None:
            return Response(data={'code': 400, 'code_text': 'days参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        share = request.query_params.get('share', None)
        if share is None:
            return Response(data={'code': 400, 'code_text': '缺少share参数'}, status=status.HTTP_400_BAD_REQUEST)

        share = str_to_int_or_default(share, -1)
        if share not in [0, 1, 2]:
            return Response(data={'code': 400, 'code_text': 'share参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            ok = hManager.share_object(bucket_name=bucket_name, obj_path=objpath, share=share, days=days, password=password, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        if not ok:
            return Response(data={'code': 500, 'code_text': '对象共享权限设置失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        share_uri = django_reverse('share:obs-detail', kwargs={'objpath': f'{bucket_name}/{objpath}'})
        if password:
            share_uri = f'{share_uri}?p={password}'
        share_uri = request.build_absolute_uri(share_uri)
        data = {
            'code': 200,
            'code_text': '对象共享权限设置成功',
            'share': share,
            'days': days,
            'share_uri': share_uri
        }
        return Response(data=data, status=status.HTTP_200_OK)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in  ['update', 'create_detail']:
            return serializers.ObjPutSerializer
        return Serializer

    def do_bucket_limit_validate(self, bfm:BucketFileManagement):
        '''
        存储桶的限制验证
        :return: True(验证通过); False(未通过)
        '''
        # 存储桶对象和文件夹数量上限验证
        if bfm.get_count() >= 10**7:
            return False

        return True

    def custom_read_param_validate_or_response(self, request):
        '''
        自定义读取文件对象参数验证
        :param request:
        :return:
                (None, None) -> 未携带参数
                (None, response) -> 参数有误
                ({data}, None) -> 参数验证通过

        '''
        chunk_offset = request.query_params.get('offset', None)
        chunk_size = request.query_params.get('size', None)

        validated_data = {}
        if chunk_offset is not None and chunk_size is not None:
            try:
                offset = int(chunk_offset)
                size = int(chunk_size)
                if offset < 0 or size < 0 or size > 20*1024**2: #20Mb
                    raise Exception()
                validated_data['offset'] = offset
                validated_data['size'] = size
            except:
                response = Response(data={'code': 400, 'code_text': 'offset或size参数有误'},
                                status=status.HTTP_400_BAD_REQUEST)
                return None, response
        # 未提交参数
        elif chunk_offset is None and chunk_size is None:
            return None, None
        # 参数提交不全
        else:
            response = Response(data={'code': 400, 'code_text': 'offset和size参数必须同时提交'},
                                status=status.HTTP_400_BAD_REQUEST)
            return None, response
        return validated_data, None

    def wrap_chunk_response(self, chunk:bytes, obj_size:int):
        '''
        文件对象自定义读取response

        :param chunk: 数据块
        :param size: 文件对象总大小
        :return: HttpResponse
        '''
        c_len = len(chunk)
        response = StreamingHttpResponse(BytesIO(chunk), status=status.HTTP_200_OK)
        response['Content-Type'] = 'application/octet-stream'  # 注意格式
        response['evob_chunk_size'] = c_len
        response['Content-Length'] = c_len
        response['evob_obj_size'] = obj_size
        return response

    def get_data(self, request):
        return request.data


class DirectoryViewSet(CustomGenericViewSet):
    '''
    目录视图集

    list:
    获取存储桶根目录下的文件和文件夹信息

        >>Http Code: 状态码200:
            {
                'code': 200,
                'files': [fileobj, fileobj, ...],//文件信息对象列表
                'bucket_name': xxx,             //存储桶名称
                'dir_path': xxx,                //当前目录路径
            }
        >>Http Code: 状态码400:
            {
                'code': 400,
                'code_text': '参数有误'
            }
        >>Http Code: 状态码404:
            {
                'code': xxx,      //404
                'code_text': xxx  //错误码描述
            }

    create_detail:
        创建一个目录

        >>Http Code: 状态码400, 请求参数有误:
            {
                "code": 400,
                "code_text": 'xxxxx'        //错误信息
                "existing": true or  false  // true表示资源已存在
            }
        >>Http Code: 状态码201,创建文件夹成功：
            {
                'code': 201,
                'code_text': '创建文件夹成功',
                'data': {},      //请求时提交的数据
                'dir': {}，      //新目录对象信息
            }

    destroy:
        删除一个目录, 目录必须为空，否则400错误

        >>Http Code: 状态码204,成功删除;
        >>Http Code: 状态码400,参数无效或目录不为空;
            {
                'code': 400,
                'code_text': 'xxx'
            }
        >>Http Code: 状态码404;
            {
                'code': 404,
                'code_text': '文件不存在
            }

    partial_update:
        设置目录访问权限

        >>Http Code: 状态码200;
        {
          "code": 200,
          "code_text": "设置目录权限成功",
          "share": "http://xxx/share/s/xx/xx" # 分享链接
        }
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'dirpath'
    lookup_value_regex = '.+'
    pagination_class = paginations.BucketFileLimitOffsetPagination

    @swagger_auto_schema(
        operation_summary='获取存储桶根目录下的文件和文件夹信息',
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "bucket_name": "666",
                  "dir_path": "",
                  "files": [
                    {
                      "na": "sacva",                    # 全路径文件或目录名称
                      "name": "sacva",                  # 文件或目录名称
                      "fod": false,                     # true: 文件；false: 目录
                      "did": 0,
                      "si": 0,                          # size byte，目录为0
                      "ult": "2019-02-20T13:56:25+08:00",     # 上传创建时间
                      "upt": null,                      # 修改时间，目录为null
                      "dlc": 0,                         # 下载次数
                      "download_url": "",               # 下载url
                      "access_permission": "公有"
                    }
                  ],
                  "count": 5,
                  "next": null,
                  "page": {
                    "current": 1,
                    "final": 1
                  },
                  "previous": null
                }
            """
        }
    )
    def list(self, request, *args, **kwargs):
        return self.list_v1(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary='获取一个目录下的文件和文件夹信息',
        manual_parameters=[
            openapi.Parameter(
                name='dirpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="目录绝对路径",
                required=True
            ),
            openapi.Parameter(
                name='offset', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="The initial index from which to return the results",
                required=False,
            ),
            openapi.Parameter(
                name='limit', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="Number of results to return per page",
                required=False,
            )
        ],
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "bucket_name": "666",
                  "dir_path": "sacva",
                  "files": [
                    {
                      "na": "sacva/client.ovpn",        # 全路径文件或目录名称
                      "name": "client.ovpn",            # 文件或目录名称
                      "fod": true,                      # true: 文件；false: 目录
                      "did": 11,
                      "si": 1185,                       # size byte，目录为0
                      "ult": "2019-02-20T13:56:25+08:00",     # 上传创建时间
                      "upt": "2019-02-20T13:56:25+08:00",     # 修改时间
                      "dlc": 1,
                      "download_url": "http://159.226.91.140:8000/share/obs/666/sacva/client.ovpn",
                      "access_permission": "公有"
                    }
                  ],
                  "count": 1,
                  "next": null,
                  "page": {
                    "current": 1,
                    "final": 1
                  },
                  "previous": null
                }
            """
        }
    )
    def list_detail(self, request, *args, **kwargs):
        '''
         获取一个目录下的文件和文件夹信息
        '''
        return self.list_v1(request, *args, **kwargs)

    def list_v1(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        dir_path = kwargs.get(self.lookup_field, '')

        paginator = self.paginator
        paginator.request = request
        try:
            offset = paginator.get_offset(request)
            limit = paginator.get_limit(request)
        except Exception as e:
            return Response(data={'code': 400, 'code_text': 'offset或limit参数无效'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            files, bucket = hManager.list_dir(bucket_name=bucket_name, path=dir_path, offset=offset, limit=limit,
                                              user=request.user, paginator=paginator)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        data_dict = OrderedDict([
            ('code', 200),
            ('bucket_name', bucket_name),
            ('dir_path', dir_path),
        ])

        serializer = self.get_serializer(files, many=True, context={'bucket_name': bucket_name, 'dir_path': dir_path, 'bucket': bucket})
        data_dict['files'] = serializer.data
        return paginator.get_paginated_response(data_dict)

    @swagger_auto_schema(
        operation_summary='创建一个目录',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='dirpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="目录绝对路径",
                required=True
            ),
        ],
        responses={
            status.HTTP_201_CREATED: """
                {
                  "code": 201,
                  "code_text": "创建文件夹成功",
                  "data": {
                    "dir_name": "aaa",
                    "bucket_name": "666",
                    "dir_path": ""
                  },
                  "dir": {
                    "na": "aaa",
                    "name": "aaa",
                    "fod": false,
                    "did": 0,
                    "si": 0,
                    "ult": "2019-02-20T13:56:25+08:00",
                    "upt": null,
                    "dlc": 0,
                    "download_url": "",
                    "access_permission": "私有"
                  }
                }
            """
        }
    )
    def create_detail(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        path = kwargs.get(self.lookup_field, '')
        hManager = HarborManager()
        try:
            ok, dir = hManager.mkdir(bucket_name=bucket_name, path=path, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        data = {
            'code': 201,
            'code_text': '创建文件夹成功',
            'data': {'dir_name': dir.name, 'bucket_name': bucket_name, 'dir_path': dir.get_parent_path()},
            'dir': serializers.ObjInfoSerializer(dir).data
        }
        return Response(data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary='删除一个目录',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='dirpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="目录绝对路径",
                required=True
            ),
        ],
        responses={
            status.HTTP_204_NO_CONTENT: 'NO CONTENT'
        }
    )
    def destroy(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        dirpath = kwargs.get(self.lookup_field, '')

        hManager = HarborManager()
        try:
            ok = hManager.rmdir(bucket_name=bucket_name, dirpath=dirpath, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @swagger_auto_schema(
        operation_summary='设置目录访问权限',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='dirpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="目录绝对路径",
                required=True
            ),
            openapi.Parameter(
                name='share', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="用于设置目录访问权限, 0（私有），1(公有只读)，2(公有可读可写)",
                required=True
            ),
            openapi.Parameter(
                name='days', in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="公开分享天数(share=1或2时有效)，0表示永久公开，负数表示不公开，默认为0",
                required=False
            ),
            openapi.Parameter(
                name='password', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="分享密码，此参数不存在，不设密码；可指定4-8字符；若为空，随机分配密码",
                required=False
            ),
        ],
        responses={
            status.HTTP_200_OK: """
                {
                  "code": 200,
                  "code_text": "设置目录权限成功",
                  "share": "http://159.226.91.140:8000/share/s/666/aaa",
                  "share_code": "ad46"          # 未设置共享密码时为空
                }
            """
        }
    )
    def partial_update(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        dirpath = kwargs.get(self.lookup_field, '')
        days = str_to_int_or_default(request.query_params.get('days', 0), 0)
        share = str_to_int_or_default(request.query_params.get('share', ''), -1)
        pw = request.query_params.get('password', None)

        if pw:  # 指定密码
            if not (4 <= len(pw) <= 8):
                return Response(data={'code': 400, 'code_text': 'password参数长度为4-8个字符'}, status=status.HTTP_400_BAD_REQUEST)
            password = pw
        elif pw is None:  # 不设密码
            password = ''
        else:  # 随机分配密码
            password = rand_share_code()

        if share not in [0, 1, 2]:
            return Response(data={'code': 400, 'code_text': 'share参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            ok = hManager.share_dir(bucket_name=bucket_name, path=dirpath, share=share,days=days, password=password, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        if not ok:
            return Response(data={'code': 400, 'code_text': '设置目录权限失败'}, status=status.HTTP_400_BAD_REQUEST)

        share_base = f'{bucket_name}/{dirpath}'
        share_url = django_reverse('share:share-view', kwargs={'share_base': share_base})
        share_url = request.build_absolute_uri(share_url)
        return Response(data={'code': 200, 'code_text': '设置目录权限成功', 'share': share_url, 'share_code': password}, status=status.HTTP_200_OK)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['create_detail', 'partial_update']:
            return Serializer
        return serializers.ObjInfoSerializer

    @log_used_time(debug_logger, 'paginate in dir')
    def paginate_queryset(self, queryset):
        return super(DirectoryViewSet, self).paginate_queryset(queryset)


class BucketStatsViewSet(CustomGenericViewSet):
    '''
        retrieve:
            存储桶资源统计

            统计存储桶对象数量和所占容量，字节

            >>Http Code: 状态码200:
                {
                    "stats": {
                      "space": 12500047770969,             # 桶内对象总大小，单位字节
                      "count": 5000004,                    # 桶内对象总数量
                    },
                    "stats_time": "2020-03-04T06:01:50+00:00", # 统计时间
                    "code": 200,
                    "bucket_name": "xxx"    # 存储桶名称
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': xxx  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'bucket_name'
    lookup_value_regex = '[a-z0-9-_]{3,64}'

    def retrieve(self, request, *args, **kwargs):
        bucket_name = kwargs.get(self.lookup_field)

        user = request.user
        if user.is_superuser:
            bucket = Bucket.get_bucket_by_name(bucket_name)
        else:
            bucket = get_user_own_bucket(bucket_name, request)

        if not bucket:
            return Response(data={'code': 404, 'code_text': 'bucket_name参数有误，存储桶不存在'},
                                  status=status.HTTP_404_NOT_FOUND)

        data = bucket.get_stats()
        data.update({
            'code': 200,
            'bucket_name': bucket_name,
        })

        return Response(data)


class SecurityViewSet(CustomGenericViewSet):
    '''
    安全凭证视图集

    retrieve:
        获取指定用户的安全凭证, 需要超级用户权限

            *注：默认只返回用户Auth Token和JWT(json web token)，如果希望返回内容包含访问密钥对，请显示携带query参数key,服务器不要求key有值

            >>Http Code: 状态码200:
                {
                  "user": {
                    "id": 3,
                    "username": "xxx"
                  },
                  "token": "xxx",
                  "jwt": "xxx",
                  "keys": [                                 # 此内容只在携带query参数key时存在
                    {
                      "access_key": "xxx",
                      "secret_key": "xxxx",
                      "user": "xxx",
                      "create_time": "2020-03-03T20:52:04.187179+08:00",
                      "state": true,                        # true(使用中) false(停用)
                      "permission": "可读可写"
                    },
                  ]
                }

            >>Http Code: 状态码400:
                {
                    'username': 'Must be a valid email.'
                }

            >>Http Code: 状态码403:
                {
                    "detail":"您没有执行该操作的权限。"
                }
        '''
    queryset = []
    permission_classes = [ permissions.IsSuperOrAppSuperUser]
    lookup_field = 'username'
    lookup_value_regex = '.+'


    @swagger_auto_schema(
        operation_summary='获取指定用户的安全凭证',
        manual_parameters=[
            openapi.Parameter(
                name='key', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="访问密钥对",
                required=False
            ),
        ]
    )
    def retrieve(self, request, *args, **kwargs):
        username = kwargs.get(self.lookup_field)
        key = request.query_params.get('key', None)

        try:
            self.validate_username(username)
        except exceptions.ValidationError as e:
            msg = e.message or 'Must be a valid email.'
            return Response({'username': msg}, status=status.HTTP_400_BAD_REQUEST)

        user = self.get_user_or_create(username)
        token, created = Token.objects.get_or_create(user=user)

        # jwt token
        jwtoken = JWTokenTool2().obtain_one_jwt(user=user)

        data = {
            'user': {
                'id': user.id,
                'username': user.username
            },
            'token': token.key,
            'jwt': jwtoken
        }

        # param key exists
        if key is not None:
            authkeys = AuthKey.objects.filter(user=user).all()
            serializer = AuthKeyDumpSerializer(authkeys, many=True)
            data['keys'] = serializer.data

        return Response(data)

    def get_user_or_create(self, username):
        '''
        通过用户名获取用户，或创建用户
        :param username:  用户名
        :return:
        '''
        try:
            user = User.objects.get(username=username)
        except exceptions.ObjectDoesNotExist:
            user = None

        if user:
            return user

        user = User(username=username, email=username)
        user.save()

        return user

    def validate_username(self, username):
        '''
        验证用户名是否是邮箱

        failed: raise ValidationError
        '''
        validate_email(username)


class MoveViewSet(CustomGenericViewSet):
    '''
    对象移动或重命名

    create_detail:
        移动或重命名一个对象

        参数move_to指定对象移动的目标路径（bucket桶下的目录路径），/或空字符串表示桶下根目录；参数rename指定重命名对象的新名称；
        请求时至少提交其中一个参数，亦可同时提交两个参数；只提交参数move_to只移动对象，只提交参数rename只重命名对象；

        >>Http Code: 状态码201,成功：
        >>Http Code: 状态码400, 请求参数有误，已存在同名的对象或目录:
            {
                "code": 400,
                "code_text": 'xxxxx'        //错误信息
            }
        >>Http Code: 状态码404, bucket桶、对象或移动目标路径不存在:
            {
                "code": 404,
                "code_text": 'xxxxx'        //错误信息
            }
        >>Http Code: 状态码500, 服务器错误，无法完成操作:
            {
                "code": 500,
                "code_text": 'xxxxx'        //错误信息
            }
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'objpath'
    lookup_value_regex = '.+'

    @swagger_auto_schema(
        operation_summary='移动或重命名一个对象',
        operation_id='v1_move_create_detail',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='objpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="文件对象绝对路径",
                required=True
            ),
            openapi.Parameter(
                name='move_to', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="移动对象到此目录路径下，/或空字符串表示桶下根目录",
                required=False
            ),
            openapi.Parameter(
                name='rename', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="重命名对象的新名称",
                required=False
            )
        ],
        responses={
            status.HTTP_201_CREATED: """
                {
                  "code": 201,
                  "code_text": "移动对象操作成功",
                  "bucket_name": "666",
                  "dir_path": "d d",
                  "obj": {                      # 移动操作成功后文件对象详细信息
                    "na": "d d/data.json2",
                    "name": "data.json2",
                    "fod": true,
                    "did": 6,
                    "si": 149888,
                    "ult": "2020-03-03T20:52:04.187179+08:00",
                    "upt": "2020-03-03T20:52:04.187179+08:00",
                    "dlc": 1,
                    "download_url": "http://159.226.91.140:8000/share/obs/666/d%20d/data.json2",
                    "access_permission": "公有"
                  }
                }
            """
        }
    )
    def create_detail(self, request, *args, **kwargs):
        bucket_name = kwargs.get('bucket_name', '')
        objpath = kwargs.get(self.lookup_field, '')
        move_to = request.query_params.get('move_to', None)
        rename = request.query_params.get('rename', None)

        hManager = HarborManager()
        try:
            obj, bucket = hManager.move_rename(bucket_name=bucket_name, obj_path=objpath, rename=rename, move=move_to, user=request.user)
        except HarborError as e:
            return Response(data={'code':e.code, 'code_text': e.msg}, status=e.code)

        context = self.get_serializer_context()
        context.update({'bucket_name': bucket.name, 'bucket': bucket})
        return Response(data={'code': 201, 'code_text': '移动对象操作成功',
                              'bucket_name': bucket.name,
                              'dir_path': obj.get_parent_path(),
                              'obj': serializers.ObjInfoSerializer(obj, context=context).data},
                        status=status.HTTP_201_CREATED)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['create_detail']:
            return Serializer
        return Serializer


class MetadataViewSet(CustomGenericViewSet):
    '''
    对象或目录元数据视图集

    retrieve:
        获取对象或目录元数据

        >>Http Code: 状态码200,成功：
            {
                "code": 200,
                "bucket_name": "xxx",
                "dir_path": "xxx",
                "code_text": "获取元数据成功",
                "obj": {
                    "na": "upload/Firefox-latest.exe",  # 对象或目录全路径名称
                    "name": "Firefox-latest.exe",       # 对象或目录名称
                    "fod": true,                        # true(文件对象)；false(目录)
                    "did": 42,                          # 父目录节点id
                    "si": 399336,                       # 对象大小，单位字节； 目录时此字段为0
                    "ult": "2019-02-20T13:56:25+08:00",       # 创建时间
                    "upt": "2019-02-20T13:56:25+08:00",       # 最后修改时间； 目录时此字段为空
                    "dlc": 2,                           # 下载次数； 目录时此字段为0
                    "download_url": "http://10.0.86.213/obs/gggg/upload/Firefox-latest.exe", # 对象下载url; 目录此字段为空
                    "access_permission": "私有"          # 访问权限，‘私有’或‘公有’； 目录此字段为空
                }
            }
        >>Http Code: 状态码400, 请求参数有误，已存在同名的对象或目录:
            {
                "code": 400,
                "code_text": 'xxxxx'        //错误信息
            }
        >>Http Code: 状态码404, bucket桶、对象或目录不存在:
            {
                "code": 404,
                "code_text": 'xxxxx'        //错误信息，
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'path'
    lookup_value_regex = '.+'


    @swagger_auto_schema(
        operation_summary='获取对象或目录元数据',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='path', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="对象或目录绝对路径",
                required=True
            )
        ],
        responses={
            status.HTTP_200_OK: ''
        }
    )
    def retrieve(self, request, *args, **kwargs):
        path_name = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name', '')
        path, name = PathParser(filepath=path_name).get_path_and_filename()
        if not bucket_name or not name:
            return Response(data={'code': 400, 'code_text': 'path参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            bucket, obj = hManager.get_bucket_and_obj_or_dir(bucket_name=bucket_name, path=path_name, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)
        except Exception as e:
            return Response(data={'code': 500, 'code_text': f'错误，{str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not obj:
            return Response(data={'code': 404, 'code_text': '对象或目录不存在'}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(obj, context={'bucket': bucket, 'bucket_name': bucket_name, 'dir_path': path})
        return Response(data={'code': 200, 'code_text': '获取元数据成功', 'bucket_name': bucket_name,
                              'dir_path': path, 'obj': serializer.data})

    @swagger_auto_schema(
        operation_summary='创建一个空对象元数据',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='path', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="对象绝对路径",
                required=True
            )
        ],
        responses={
            status.HTTP_200_OK: """
            {
              "code": 200,
              "code_text": "创建空对象元数据成功",
              "info": {
                "rados": "iharbor:ceph/obs_test/471_5",
                "size": 0,
                "filename": "test2.txt"
              },
              "obj": {
                "na": "test5",
                "name": "test5",
                "fod": true,
                "did": 0,
                "si": 0,
                "ult": "2020-03-04T14:21:01.422096+08:00",
                "upt": null,
                "dlc": 0,
                "download_url": "http://xxx/share/obs/6666/test5",
                "access_permission": "私有"
              }
            }
            """
        }
    )
    def create_detail(self, request, *args, **kwargs):
        path_name = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name', '')
        path, name = PathParser(filepath=path_name).get_path_and_filename()
        if not bucket_name or not name:
            return Response(data={'code': 400, 'code_text': 'path参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            bucket, obj, created = hManager.create_empty_obj(bucket_name=bucket_name, obj_path=path_name, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)
        except Exception as e:
            return Response(data={'code': 500, 'code_text': f'错误，{str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not obj or not created:
            return Response(data={'code': 404, 'code_text': '创建失败，对象已存在'}, status=status.HTTP_404_NOT_FOUND)

        obj_key = obj.get_obj_key(bucket.id)
        pool_name = bucket.get_pool_name()
        ho = HarborObject(pool_name=pool_name, obj_id=obj_key, obj_size=obj.obj_size)
        rados_key = ho.get_rados_key_info()
        info = {
            'rados': rados_key,
            'size': obj.obj_size,
            'filename': obj.name
        }
        serializer = self.get_serializer(obj, context={'bucket': bucket, 'bucket_name': bucket_name, 'dir_path': path})
        return Response(data={'code': 200, 'code_text': '创建空对象元数据成功', 'info': info, 'obj': serializer.data})

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action in ['retrieve', 'create_detail']:
            return serializers.ObjInfoSerializer
        return Serializer


class RefreshMetadataViewSet(CustomGenericViewSet):
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'path'
    lookup_value_regex = '.+'

    @swagger_auto_schema(
        operation_summary='自动同步对象大小元数据',
        operation_id='v1_refresh-meta_create_detail',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='path', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="对象绝对路径",
                required=True
            )
        ],
        responses={
            status.HTTP_200_OK: ''
        }
    )
    def create_detail(self, request, *args, **kwargs):
        """
        自动更新对象大小元数据

            警告：特殊API，未与技术人员沟通不可使用；对象大小2GB内适用

            >>Http Code: 状态码200,成功：
                {
                  "code": 200,
                  "code_text": "更新对象大小元数据成功",
                  "info": {
                    "size": 867840,
                    "filename": "7zFM.exe",
                    "mtime": "2020-03-04T08:05:28.210658+00:00"     # 修改时间
                  }
                }
            >>Http Code: 状态码400, 请求参数有误，已存在同名的对象或目录:
                {
                    "code": 400,
                    "code_text": 'xxxxx'        //错误信息
                }
            >>Http Code: 状态码404, bucket桶、对象或目录不存在:
                {
                    "code": 404,
                    "code_text": 'xxxxx'        //错误信息，
        """
        path_name = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name', '')
        path, name = PathParser(filepath=path_name).get_path_and_filename()
        if not bucket_name or not name:
            return Response(data={'code': 400, 'code_text': 'path参数有误'}, status=status.HTTP_400_BAD_REQUEST)

        hManager = HarborManager()
        try:
            bucket, obj = hManager.get_bucket_and_obj(bucket_name=bucket_name, obj_path=path_name, user=request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)
        except Exception as e:
            return Response(data={'code': 500, 'code_text': f'错误，{str(e)}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not obj:
            return Response(data={'code': 404, 'code_text': '对象不存在'}, status=status.HTTP_404_NOT_FOUND)

        obj_key = obj.get_obj_key(bucket.id)
        pool_name = bucket.get_pool_name()
        ho = HarborObject(pool_name=pool_name, obj_id=obj_key, obj_size=obj.obj_size)
        ok, ret = ho.get_rados_stat(obj_id=obj_key)
        if not ok:
            return Response(data={'code': 400, 'code_text': f'获取rados对象大小失败，{ret}'}, status=status.HTTP_400_BAD_REQUEST)

        size, mtime = ret
        if size == 0 and mtime is None:  # rados对象不存在
            mtime = obj.upt if obj.upt else obj.ult
            mtime = to_django_timezone(mtime)

        if obj.upt != mtime:
            pass
        if obj.si != size or obj.upt != mtime:
            obj.si = size
            obj.upt = mtime
            try:
                obj.save(update_fields=['si', 'upt'])
            except Exception as e:
                return Response(data={'code': 400, 'code_text': f'更新对象大小元数据失败，{str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        info = {
            'size': size,
            'filename': obj.name,
            'mtime': mtime.isoformat()
        }
        return Response(data={'code': 200, 'code_text': '更新对象大小元数据成功', 'info': info})


class CephStatsViewSet(CustomGenericViewSet):
    '''
        ceph集群视图集

        list:
            CEPH集群资源统计

            统计ceph集群总容量、已用容量，可用容量、对象数量

            >>Http Code: 状态码200:
                {
                  "code": 200,
                  "code_text": "successful",
                  "stats": {
                    "kb": 762765762560,     # 总容量，单位kb
                    "kb_used": 369591170304,# 已用容量
                    "kb_avail": 393174592256,# 可用容量
                    "num_objects": 40750684  # rados对象数量
                  }
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }

            >>Http Code: 状态码500:
                {
                    'code': 500,
                    'code_text': xxx  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        try:
            stats = HarborObject(pool_name='', obj_id='').get_cluster_stats()
        except RadosError as e:
            return Response(data={'code': 500, 'code_text': '获取ceph集群信息错误：' + str(e)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'code': 200,
            'code_text': 'successful',
            'stats': stats
        })


class UserStatsViewSet(CustomGenericViewSet):
    '''
        用户资源统计视图集

        retrieve:
            获取指定用户的资源统计信息

            获取指定用户的资源统计信息，需要超级用户权限

             >>Http Code: 状态码200:
            {
                "code": 200,
                "space": 12991806596545,  # 已用总容量，byte
                "count": 5864125,         # 总对象数量
                "buckets": [              # 每个桶的统计信息
                    {
                        "stats": {
                            "space": 16843103, # 桶内对象总大小，单位字节
                            "count": 4          # 桶内对象总数量
                        },
                        "stats_time": "2020-03-04T14:21:01.422096+08:00", # 统计时间
                        "bucket_name": "wwww"       # 存储桶名称
                    },
                    {
                        "stats": {
                            "space": 959820827,
                            "count": 17
                        },
                        "stats_time": "2020-03-04T06:01:50+00:00",
                        "bucket_name": "gggg"
                    },
                ]
            }

        list:
            获取当前用户的资源统计信息

            获取当前用户的资源统计信息

            >>Http Code: 状态码200:
            {
                "code": 200,
                "space": 12991806596545,  # 已用总容量，byte
                "count": 5864125,         # 总对象数量
                "buckets": [              # 每个桶的统计信息
                    {
                        "stats": {
                            "space": 16843103, # 桶内对象总大小，单位字节
                            "count": 4          # 桶内对象总数量
                        },
                        "stats_time": "2020-03-04T06:01:50+00:00", # 统计时间
                        "bucket_name": "wwww"       # 存储桶名称
                    },
                    {
                        "stats": {
                            "space": 959820827,
                            "count": 17
                        },
                        "stats_time": "2020-03-04T06:01:50+00:00",
                        "bucket_name": "gggg"
                    },
                ]
            }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': xxx  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'username'
    lookup_value_regex = '.+'
    pagination_class = None

    def list(self, request, *args, **kwargs):
        user = request.user
        data = self.get_user_stats(user)
        data['code'] = 200
        data['username'] = user.username
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        username = kwargs.get(self.lookup_field)
        try:
            user = User.objects.get(username=username)
        except exceptions.ObjectDoesNotExist:
            return Response(data={'code': 404, 'code_text': 'username参数有误，用户不存在'},
                            status=status.HTTP_404_NOT_FOUND)

        data = self.get_user_stats(user)
        data['code'] = 200
        data['username'] = user.username
        return Response(data)

    def get_user_stats(self, user):
        '''获取用户的资源统计信息'''
        all_count = 0
        all_space = 0
        li = []
        buckets = Bucket.objects.filter(user=user)
        for b in buckets:
            s = b.get_stats()
            s['bucket_name'] = b.name
            li.append(s)

            stats = s.get('stats', {})
            all_space += stats.get('space', 0)
            all_count += stats.get('count', 0)

        return {
            'space': all_space,
            'count': all_count,
            'buckets': li
        }

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action =='retrieve':
            return [permissions.IsSuperUser()]

        return super(UserStatsViewSet, self).get_permissions()


class CephComponentsViewSet(CustomGenericViewSet):
    '''
        ceph集群组件信息视图集

        list:
            ceph的mon，osd，mgr，mds组件信息

            需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    "mon": {},
                    "osd": {},
                    "mgr": {},
                    "mds": {}
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        return Response({
            'code': 200,
            'mon': {},
            'osd': {},
            'mgr': {},
            'mds': {}
        })


class CephErrorViewSet(CustomGenericViewSet):
    '''
        ceph集群当前故障信息查询

        list:
            ceph集群当前故障信息查询

            需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    'errors': {
                    }
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        return Response({
            'code': 200,
            'errors': {

            }
        })


class CephPerformanceViewSet(CustomGenericViewSet):
    '''
        ceph集群性能，需要超级用户权限

        list:
            ceph集群的IOPS，I/O带宽

            需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "bw_rd": 0,     # Kb/s, io读带宽
                    "bw_wr": 4552,  # Kb/s, io写带宽
                    "bw": 4552,     # Kb/s, io读写总带宽
                    "op_rd": 220,   # op/s, io读操作数
                    "op_wr": 220,   # op/s, io写操作数
                    "op": 441       # op/s, io读写操作数
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        ok, data = HarborObject(pool_name='', obj_id='').get_ceph_io_status()
        if not ok:
            return Response(data={'code': 500, 'code_text': 'Get io status error:' + data}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(data=data)


class UserCountViewSet(CustomGenericViewSet):
    '''
        系统用户总数查询

        list:
            系统用户总数查询

            系统用户总数查询，需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    'count': xxx
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        count = User.objects.filter(is_active=True).count()
        return Response({
            'code': 200,
            'count': count
        })


class AvailabilityViewSet(CustomGenericViewSet):
    '''
        系统可用性

        list:
            系统可用性查询

            系统可用性查询，需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    'availability': '100%'
                }
        '''
    queryset = None
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        return Response({
            'code': 200,
            'availability': '100%'
        })


class VisitStatsViewSet(CustomGenericViewSet):
    '''
        访问统计

        list:
            系统访问统计查询

            系统访问统计查询，需要超级用户权限

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    "stats": {
                        "active_users": 100,  # 日活跃用户数
                        "register_users": 10,# 日注册用户数
                        "visitors": 100,    # 访客数
                        "page_views": 1000,  # 访问量
                        "ips": 50           # IP数
                    }
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = [permissions.IsSuperUser]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        stats = User.active_user_stats()
        stats.update({
            'visitors': 100,
            'page_views': 1000,
            'ips': 50
        })
        return Response({
            'code': 200,
            'stats': stats
        })


class TestViewSet(CustomGenericViewSet):
    '''
        系统是否可用查询

        list:
            系统是否可用查询

            系统是否可用查询

            >>Http Code: 状态码200:
                {
                    "code": 200,
                    "code_text": "系统可用",
                    "status": true     # true: 可用；false: 不可用
                }

            >>Http Code: 状态码404:
                {
                    'code': 404,
                    'code_text': URL中包含无效的版本  //错误码描述
                }
        '''
    queryset = []
    permission_classes = []
    throttle_classes = (throttles.TestRateThrottle,)
    pagination_class = None

    def list(self, request, *args, **kwargs):
        return Response({
            'code': 200,
            'code_text': '系统可用',
            'status': True     # True: 可用；False: 不可用
        })


class FtpViewSet(CustomGenericViewSet):
    '''
    存储桶FTP服务配置相关API

    partial_update:
    开启或关闭存储桶ftp访问限制，开启存储桶的ftp访问权限后，可以通过ftp客户端访问存储桶

        Http Code: 状态码200，返回数据：
        {
            "code": 200,
            "code_text": "ftp配置成功"，
            "data": {               # 请求时提交的数据
                "enable": xxx,      # 此项提交时才存在
                "password": xxx     # 此项提交时才存在
                "ro_password": xxx     # 此项提交时才存在
            }
        }
        Http Code: 状态码400：参数有误时，返回数据：
            对应参数错误信息;
        Http Code: 状态码404;
        Http Code: 500
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    lookup_field = 'bucket_name'
    lookup_value_regex = '[a-z0-9-_]{3,64}'
    pagination_class = None


    @swagger_auto_schema(
        operation_summary='开启或关闭存储桶ftp访问限制',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='bucket_name', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="存储桶名称",
                required=True
            ),
            openapi.Parameter(
                name='enable', in_=openapi.IN_QUERY,
                type=openapi.TYPE_BOOLEAN,
                description="存储桶ftp访问,true(开启)；false(关闭)",
                required=False
            ),
            openapi.Parameter(
                name='password', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="存储桶ftp新的读写访问密码",
                required=False
            ),
            openapi.Parameter(
                name='ro_password', in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="存储桶ftp新的只读访问密码",
                required=False
            ),
        ],
        responses={
            status.HTTP_200_OK: ''
        }
    )
    def partial_update(self, request, *args, **kwargs):
        bucket_name = kwargs.get(self.lookup_field, '')
        if not bucket_name:
            return Response(data={'code': 400, 'code_text': '桶名称有误'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            params = self.validate_patch_params(request)
        except ValidationError as e:
            return Response(data={'code': 400, 'code_text': e.detail}, status=status.HTTP_400_BAD_REQUEST)

        enable = params.get('enable')
        password = params.get('password')
        ro_password = params.get('ro_password')

        # 存储桶验证和获取桶对象
        bucket = get_user_own_bucket(bucket_name=bucket_name, request=request)
        if not bucket:
            return Response(data={'code': 404, 'code_text': 'bucket_name参数有误，存储桶不存在'},
                            status=status.HTTP_404_NOT_FOUND)

        data = {}
        if enable is not None:
            bucket.ftp_enable = enable
            data['enable'] = enable

        if password is not None:
            ok, msg = bucket.set_ftp_password(password)
            if not ok:
                return Response(data={'code': 400, 'code_text': msg}, status=status.HTTP_400_BAD_REQUEST)
            data['password'] = password

        if ro_password is not None:
            ok, msg = bucket.set_ftp_ro_password(ro_password)
            if not ok:
                return Response(data={'code': 400, 'code_text': msg}, status=status.HTTP_400_BAD_REQUEST)
            data['ro_password'] = ro_password

        try:
            bucket.save()
        except Exception as e:
            return Response(data={'code': 500, 'code_text': 'ftp配置失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'code': 200,
            'code_text': 'ftp配置成功',
            'data': data     # 请求提交的参数
        })

    def validate_patch_params(self, request):
        '''
        patch请求方法参数验证
        :return:
            {
                'enable': xxx, # None(未提交此参数) 或 bool
                'password': xxx   # None(未提交此参数) 或 string
            }
        '''
        validated_data = {'enable': None, 'password': None, 'ro_password': None}
        enable = request.query_params.get('enable', None)
        password = request.query_params.get('password', None)
        ro_password = request.query_params.get('ro_password', None)

        if not enable and not password and not ro_password:
            raise ValidationError('参数enable,password或ro_password必须提交一个')

        if enable is not None:
            if isinstance(enable, str):
                enable = enable.lower()
                if enable == 'true':
                    enable = True
                elif enable == 'false':
                    enable = False
                else:
                    raise ValidationError('无效的enable参数')

            validated_data['enable'] = enable

        if password is not None:
            password = password.strip()
            if not (6 <= len(password) <= 20):
                raise ValidationError('密码长度必须为6-20个字符')

            validated_data['password'] = password

        if ro_password is not None:
            ro_password = ro_password.strip()
            if not (6 <= len(ro_password) <= 20):
                raise ValidationError('密码长度必须为6-20个字符')

            validated_data['ro_password'] = ro_password

        return validated_data

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        return Serializer


class VPNViewSet(CustomGenericViewSet):
    '''
    VPN相关API
    '''
    queryset = []
    permission_classes = [IsAuthenticated]
    pagination_class = None


    @swagger_auto_schema(
        operation_summary='获取VPN口令',
        responses={
            status.HTTP_200_OK: ''
        }
    )
    def list(self, request, *args, **kwargs):
        '''
        获取VPN口令信息

            Http Code: 状态码200，返回数据：
            {
                "code": 200,
                "code_text": "获取成功",
                "vpn": {
                    "id": 2,
                    "password": "2523c77e7b",
                    "created_time": "2020-03-04T06:01:50+00:00",
                    "modified_time": "2020-03-04T06:01:50+00:00",
                    "user": {
                        "id": 3,
                        "username": "869588058@qq.com"
                    }
                }
            }
        '''
        vpn, created = VPNAuth.objects.get_or_create(user=request.user)
        return Response(data={'code': 200, 'code_text': '获取成功', 'vpn': serializers.VPNSerializer(vpn).data})

    @swagger_auto_schema(
        operation_summary='修改vpn口令',
        responses={
            status.HTTP_201_CREATED: """
                {
                    "code": 201,
                    "code_text": "修改成功"
                }
            """,
            status.HTTP_400_BAD_REQUEST: """
                    {
                        "code": 400,
                        "code_text": "xxxx"
                    }
                """
        }
    )
    def create(self, request, *args, **kwargs):
        '''
        修改vpn口令
        '''
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid(raise_exception=False):
            code_text = 'password有误'
            try:
                for key, err_list in serializer.errors.items():
                    code_text = f'{key},{err_list[0]}'
                    break
            except:
                pass
            return Response(data={'code': 400, 'code_text': code_text}, status=status.HTTP_400_BAD_REQUEST)

        password = serializer.validated_data['password']
        vpn, created = VPNAuth.objects.get_or_create(user=request.user)
        if vpn.reset_password(password):
            return Response(data={'code': 201, 'code_text': '修改成功', 'vpn': serializers.VPNSerializer(vpn).data}, status=status.HTTP_201_CREATED)

        return Response(data={'code': 400, 'code_text': '修改失败'}, status=status.HTTP_400_BAD_REQUEST)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        Custom serializer_class
        """
        if self.action == 'create':
            return serializers.VPNPostSerializer
        return Serializer


class ObjKeyViewSet(CustomGenericViewSet):
    '''
    对象CEPH RADOS KEY视图集

    retrieve:
        获取对象对应的ceph rados key信息

    	>>Http Code: 状态码200：
            {
                "code": 200,
                "code_text": "请求成功",
                "info": {
                    "rados": "iharbor:ceph/obs/217_12", # 对象对应rados信息，格式：iharbor:{cluster_name}/{pool_name}/{rados-key}
                    "size": 1185,                       # 对象大小Byte
                    "filename": "client.ovpn"           # 对象名称
                }
            }

        >>Http Code: 状态码400：文件路径参数有误：对应参数错误信息;
            {
                'code': 400,
                'code_text': 'xxxx参数有误'
            }
        >>Http Code: 状态码404：找不到资源;
        >>Http Code: 状态码500：服务器内部错误;

    '''
    queryset = {}
    permission_classes = [IsAuthenticated]
    lookup_field = 'objpath'
    lookup_value_regex = '.+'


    @swagger_auto_schema(
        operation_summary='获取对象对应的ceph rados key信息',
        request_body=no_body,
        manual_parameters=[
            openapi.Parameter(
                name='objpath', in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                description="文件对象绝对路径",
                required=True
            )
        ]
    )
    def retrieve(self, request, *args, **kwargs):
        objpath = kwargs.get(self.lookup_field, '')
        bucket_name = kwargs.get('bucket_name','')

        hManager = HarborManager()
        try:
            bucket, obj = hManager.get_bucket_and_obj(bucket_name=bucket_name, obj_path=objpath, user = request.user)
        except HarborError as e:
            return Response(data={'code': e.code, 'code_text': e.msg}, status=e.code)

        if not obj:
            return Response(data={'code': 404, 'code_text': '对象不存在'}, status=status.HTTP_404_NOT_FOUND)

        obj_key = obj.get_obj_key(bucket.id)
        pool_name = bucket.get_pool_name()
        rados_key = HarborObject(pool_name=pool_name, obj_id=obj_key, obj_size=obj.obj_size).get_rados_key_info()
        info = {
            'rados': rados_key,
            'size': obj.obj_size,
            'filename': obj.name
        }
        return Response(data={'code': 200, 'code_text': '请求成功', 'info': info}, status=status.HTTP_200_OK)

