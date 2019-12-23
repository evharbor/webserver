from django.urls import path
from django.contrib.auth.decorators import login_required

from . import views

app_name = "buckets"

urlpatterns = [
    path('', login_required(views.BucketView.as_view()), name='bucket_view'),
    path('usage/', views.UsageView.as_view(), name='api-usage'),
    path('ftp-usage/', views.FTPUsageView.as_view(), name='ftp-usage'),
]


