from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views


app_name = "share"
# Create a router and register our viewsets with it.
router = DefaultRouter(trailing_slash=False)
router.register(r'', views.ObsViewSet, base_name='obs')


urlpatterns = [
    path('', include(router.urls)), # The API URLs are now determined automatically by the router.
]

