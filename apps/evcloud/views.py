import datetime

from django.shortcuts import render
from django.http import JsonResponse
from django.views import View
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext as _

from .models import (EvcloudVM, VMLimit, VMConfig, APIAuth, VMUsageDescription)
from .manager import evcloud_operations


def evcloud_list(request):
    if request.method == "GET":
        user = request.user
        vm_list = EvcloudVM.objects.filter(user=user).filter(deleted=False).values()
        vm_list_dict = {}
        for i, vm in enumerate(vm_list):
            vm['created_time_display'] = vm['created_time'].strftime("%Y-%m-%d")
            vm['end_time_display'] = vm['end_time'].strftime("%Y-%m-%d")
            vm['api_display'] = APIAuth.objects.get(id=vm['api_id']).description
            vm_list_dict[i] = vm
        return render(request, 'evcloud_list.html', {'vm_list_dict':vm_list_dict})

    elif request.method == "POST":
        vm_api = int(request.POST.get('api'))
        vms = evcloud_operations(api=vm_api)
        vm_id = request.POST.get('vm_id')
        vm_operate = int(request.POST.get('vm_operate'))
        if vm_operate == 4:
            code, e = vms.delete(vm_id)
            status = 'delete'
            if code == 200:
                vm = EvcloudVM.objects.get(vm_id=vm_id)
                vm.deleted = True
                vm.save()
        elif vm_operate == 5:
            code, e = vms.create_vnc(vm_id)
            status = 'ok'
        elif vm_operate == 6:
            code, e = vms.get_status(vm_id)
            status = 'ok'
        elif vm_operate == 7:
            image_list = vms.get_image_list()
            return JsonResponse(data=image_list)
        elif 0 < vm_operate < 3:
            code, e = vms.operations(vm_id, vm_operate)
            status = '关机'
        else:
            code, e = vms.operations(vm_id, vm_operate)
            status = '开机'
        result = {
            'code': code,
            'status': status,
            'e': e,
        }
        #print(e)
        return JsonResponse(data=result)


def evcloud_add(request):
    #print(request.method)
    user = request.user
    if request.method == "GET":
        api_list = APIAuth.objects.filter(flag=True)
        config_list = VMConfig.objects.all()

        image_list = []
        try:
            image_list = evcloud_operations(api=api_list[0].id).get_image_list()
        except:
            image_list.append({'name': '服务出错'})
            pass

        return render(request, 'evcloud_add.html', {'config_list_dict': config_list,
                                                    'image_list': image_list,
                                                    'api_list_dict': api_list,
                                                    })

    elif request.method == "POST":
        api_id = int(request.POST.get('api'))
        try:
            api = APIAuth.objects.get(id=api_id)
            limit = VMLimit.objects.filter(user=user).filter(api=api)[0].limit
        except :
            VMLimit.objects.create(user=user, limit=api.limit, api=api)
            limit = api.limit
        result = {}
        image, image_name = request.POST.get('image').split('_', 1)
        image = int(image)
        config_id = int(request.POST.get('configure'))
        config = VMConfig.objects.get(id=config_id)
        cpu = config.cpu
        mem = config.mem
        time = config.time * 30
        try:
            vm_number = EvcloudVM.objects.filter(user=user).filter(deleted=False).filter(api=api).count()
            if vm_number >= limit:
                raise Exception('the number of VM exceed limit')
            # vms = evcloud_operations(api=api_id)
            # create_result = vms.create(image, cpu, mem, user.email)
            create_result = evcloud_operations(api=api_id).create(image, cpu, mem, user.email)
            EvcloudVM.objects.create(vm_id=create_result['uuid'],
                                     user=user,
                                     end_time=datetime.datetime.now()+datetime.timedelta(days=time),
                                     vm_image=image,
                                     vm_image_name=image_name,
                                     vm_cpu=cpu,
                                     vm_mem=mem,
                                     vm_ip=create_result['ipv4'],
                                     group_id=create_result['group_id'],
                                     api=api )
            #print(create_result)
            result['code'] = 200
        except Exception as e:
            result['code'] = 400
            print(e)
            result['error_text'] = str(e).encode('utf-8').decode('unicode_escape')
        return JsonResponse(data = result)
    else:
        return JsonResponse(data = 'error')


class UsageView(View):
    '''
    VM使用说明类视图
    '''
    def get(self, request, *args, **kwargs):
        article = VMUsageDescription.objects.first()
        return render(request, 'base_usage_article.html', context={'article': article})


class VMRemarksView(View):
    '''
    vm备注类视图
    '''
    def post(self, request, *args, **kwargs):
        ok, ret = self.post_validate(request)
        if not ok:
            return ret

        vm_id = ret.get('vm_id')
        remarks = ret.get('remarks')
        try:
            vm = EvcloudVM.objects.get(vm_id=vm_id)
        except ObjectDoesNotExist as e:
            return JsonResponse({'code': 404, 'code_text': '虚拟机不存在'}, status=404)

        vm.remarks = remarks
        try:
            vm.save()
        except:
            return JsonResponse({'code': 500, 'code_text': '虚拟机备注信息修改失败'}, status=500)

        return JsonResponse({'code': 200, 'code_text': '虚拟机备注信息修改成功'}, status=200)

    def post_validate(self, request):
        '''
        请求参数验证
        :param request:
        :return:
            success: True, { data }
            failed: False, JsonResponse()
        '''
        vm_id = request.POST.get('vm_id', None)
        remarks = request.POST.get('remarks', None)
        if not vm_id or not remarks:
            return False, JsonResponse({'code': 400, 'code_text': '错误的请求，vm_id或者remarks参数未提交'}, status=400)

        if not isinstance(remarks, str) or not isinstance(vm_id, str):
            return False, JsonResponse({'code': 400, 'code_text': '错误的请求，vm_id或者remarks参数有误'}, status=400)

        return True, {'vm_id': vm_id, 'remarks': remarks}
