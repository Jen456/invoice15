#=========================================================================#
# FacturaPorAquí — landing estática (HTTP). Plantilla nginx propia de Hestia #
# (deploy/hestia/nginx/fpa-landing.tpl). Todo va a https://dominio raíz;    #
# el reto ACME de Let's Encrypt sigue funcionando (nginx.conf_letsencrypt). #
#=========================================================================#

server {
	listen      %ip%:%proxy_port%;
	server_name %domain_idn% %alias_idn%;
	error_log   /var/log/%web_system%/domains/%domain%.error.log error;

	include %home%/%user%/conf/web/%domain%/nginx.forcessl.conf*;

	location ~ /\.(?!well-known\/) {
		deny all;
		return 404;
	}

	location / {
		return 301 https://%domain_idn%$request_uri;
	}

	include %home%/%user%/conf/web/%domain%/nginx.conf_*;
}
