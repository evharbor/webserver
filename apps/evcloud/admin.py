from django.contrib import admin
from .models import (VMLimit, VMConfig, APIAuth, EvcloudVM, VMUsageDescription)


@admin.register(VMLimit)
class VMLimitAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'api', 'limit')
    list_display_links = ('id', 'user', 'api', 'limit')
    list_filter = ('limit',)
    search_fields = ('user__username',)
    raw_id_fields = ('user',)


@admin.register(VMConfig)
class VMConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'cpu', 'mem', 'time')
    list_display_links = ('id', 'cpu', 'mem', 'time')
    list_filter = ('cpu', 'mem', 'time')


@admin.register(APIAuth)
class APIAuthAdmin(admin.ModelAdmin):
    list_display = ('id', 'url', 'name', 'pwd', 'group_id', 'vlan_id', 'center_id', 'description', 'limit', 'flag')
    list_display_links = ('id', 'url', 'name', 'pwd', 'group_id', 'vlan_id', 'center_id', 'description', 'limit', 'flag')
    list_filter = ('url', 'name', 'pwd', 'flag')


@admin.register(EvcloudVM)
class EvcloudVMAdmin(admin.ModelAdmin):
    list_display = ('vm_id', 'user', 'created_time', 'end_time', 'api', 'deleted')
    list_display_links = ('vm_id', 'user', 'created_time', 'end_time', 'api', 'deleted')
    list_filter = ('deleted', 'created_time', 'end_time')
    search_fields = ('user__username', 'vm_id')
    raw_id_fields = ('user',)


@admin.register(VMUsageDescription)
class VMUsageDescAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'modified_time')
    list_display_links = ('id', 'title')
    search_fields = ('title', 'content')  # 搜索字段

