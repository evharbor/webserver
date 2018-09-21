from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from . import views

urlpatterns = [
    url(r'^bucket/(?P<bucket_name>[\w-]{1,50})/(?P<path>.*)', views.file_list, name='file_list'),
    url(r'^$', login_required(views.BucketView.as_view()), name='bucket_view'),
    url(r'^download/(?P<id>[\w-]{24,32})/', views.download, name='download'),
    url(r'^delete/(?P<id>[\w-]{24,32})/', views.delete, name='delete'),
]


