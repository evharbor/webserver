from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from . import views

urlpatterns = [
    # url(r'^bucket/(?P<bucket_name>[\w-]{1,50})/(?P<path>.*)', login_required(views.FileView.as_view()), name='file_list'),
    # url(r'^object/(?P<bucket_name>[\w-]{1,50})/(?P<path>.*)/(?P<object_name>.*)', login_required(
    #     views.FileObjectView.as_view()), name='object_view'),
    # url(r'^get/(?P<bucket_name>[\w-]{1,50})/(?P<path>.*)/(?P<object_name>.*)', login_required(
    #     views.GetFileObjectView.as_view()), name='get_object_view'),
    url(r'^$', login_required(views.BucketView.as_view()), name='bucket_view'),
    url(r'^usage/', views.UsageView.as_view(), name='usage'),
]


