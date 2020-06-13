from django.shortcuts import render, redirect
from .models import Service_model, Designs, Project
from website.forms import contactusForm

# Create your views here.

def index(request):
    services = Service_model.objects.all()
    designs = Designs.objects.all()
    projects = Project.objects.all()
    # context = {
    #     'services' : services,
    #     'designs' : designs,
    #     'projects' : projects,
    #     'forms' : contactusForm(),
    # }
    return render(request, 'index.html', {"services" : services, "form" : contactusForm()})


def savedet(request):
    cs = contactusForm(request.POST)
    if cs.is_valid():
        cs.save()
        return redirect('index')
    else:
        return render(request, 'fail.html')