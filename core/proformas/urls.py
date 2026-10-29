from django.urls import path

from core.proformas import views

# Las rutas de escritura por GET llevan /add/, /update/ o /delete/: PlanMiddleware las bloquea con el plan vencido.
urlpatterns = [
    path('', views.ProformaListView.as_view(), name='proforma_list'),
    path('add/', views.ProformaCreateView.as_view(), name='proforma_create'),
    path('update/<int:pk>/', views.ProformaUpdateView.as_view(), name='proforma_update'),
    path('ver/<int:pk>/', views.ProformaDetailView.as_view(), name='proforma_detail'),
    path('delete/<int:pk>/', views.ProformaDeleteView.as_view(), name='proforma_delete'),
    path('pdf/<int:pk>/', views.ProformaPdfView.as_view(), name='proforma_pdf'),
]
