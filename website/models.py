from django.db import models


class Service_model(models.Model):
    title = models.CharField(max_length=50)
    description = models.CharField(max_length=500)
    image = models.ImageField(upload_to='images')
    url = models.URLField(blank=True)

    def __str__(self):
        return self.title


class TeamMember(models.Model):
    title=models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    image = models.ImageField(upload_to='images')

    def __str__(self):
        return self.title


class Designs(models.Model):
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    image = models.ImageField(upload_to='images')

    def __str__(self):
        return self.title


class Project(models.Model):
    Title = models.CharField(max_length=30)
    TYPE = {
        ('Office', 'Office'),
        ('Residential', 'Residential'),
        ('Commercial', 'Commercial')
    }
    type = models.CharField(null=True, choices=TYPE, max_length=200)
    description = models.CharField(max_length=500)
    image= models.ImageField(upload_to='images')

    def __str__(self):
        return self.Title

class contactus(models.Model):
    Name = models.CharField(max_length=50)
    Email = models.EmailField(unique=True)
    ContactNo = models.IntegerField()
    Message = models.CharField(max_length=1000)

class ContactusModel(models.Model):
    Name = models.CharField(max_length=50)
    Email = models.EmailField(unique=True)
    ContactNo = models.IntegerField()
    Message = models.CharField(max_length=1000)