from django.contrib import admin
from .models import Service_model, TeamMember, ContactusModel
from .models import Project

# Register your models here.

admin.site.register(Service_model)
admin.site.register(TeamMember)
admin.site.register(Project)
admin.site.register(ContactusModel)

