from django.urls import path

from core.login import registro

urlpatterns = [
    path('', registro.RegistroView.as_view(), name='registro'),
    path('enviado/', registro.RegistroEnviadoView.as_view(), name='registro_enviado'),
    path('confirmar/<str:token>/', registro.confirmar, name='registro_confirmar'),
    path('reenviar/', registro.ReenviarConfirmacionView.as_view(), name='registro_reenviar'),
]
