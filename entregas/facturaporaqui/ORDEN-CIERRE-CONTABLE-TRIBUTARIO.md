# Orden de trabajo para terminar Contabilidad y Tributario

13/11/2026 · Preparada para Claude. Base revisada `96d39e1`; no sustituye la corrección R1–R3 de `fase/primera-entrega` ni incluye esa rama sin revisar.

El precio pendiente no debe detener la construcción. Mantén separados desarrollo técnico, validación del contador y activación comercial. No resuelvas el pedido quitando el aviso o abriendo indiscriminadamente el complemento.

1. Implementa C1, C2 y C3 de `CONTRATO-CONTABLE-V9.md`: inicio, cuentas por empresa e importación con vista previa. El contador puede traer su plan; la plantilla Supercias no bloquea el motor genérico.
2. Acuerda e implementa `CONTRATO-APERTURA-CONTABLE.md` (C6-A): dos inicios por empresa, **saldos de apertura** o **historial detallado**. No exigir años de documentos a quien trae estados financieros; no inventar saldos/fechas. Mantener auxiliares y cobertura tributaria diferenciados.
3. Completa motor de asientos, reglas configurables por vigencia, vínculo a origen, idempotencia, reversos, diario, mayor y balance de comprobación. Implementa el motor aunque las cuentas definitivas de una empresa estén pendientes; las reglas no aprobadas quedan como excepciones, sin contabilización ficticia.
4. Completa bancos/conciliación y cierre/reapertura, con permisos y motivo. CSV con mapeo genérico puede avanzar mientras llegan formatos bancarios específicos. Apertura, cartera e inventario deben reconciliarse sin duplicarse.
5. Reutiliza libros, revisión, ATS y borradores 104/103 existentes. Cierra las preguntas del contador por criterio y fuente oficial; integra saldos anteriores confirmados, trazabilidad por casillero, conciliación y evidencias C5. Preparado/validado/presentado son estados distintos.
6. Completa estados financieros y preparación del 101 desde un ejercicio con apertura/resultados acumulados, mayor y conciliación tributaria. Un estado de situación aislado no justifica un 101 completo. Obligaciones Supercias/ADI solo según perfil y datos aplicables.
7. Sustituye el bloqueo genérico por un contrato de capacidades que distinga licencia, permiso, módulo pendiente y datos por completar. No cambies precios ni cobertura por inferencia; el piloto y el acceso comercial se habilitan bajo la autorización y condiciones correspondientes.
8. Prueba empresa/permisos, cuentas/ciclos, corte de apertura, histórico solapado, cobros sobre cartera inicial, stock inicial, doble envío, reversos y exportaciones. SQLite y PostgreSQL sobre el código final, navegador con datos ficticios y ensayo de migración compatible con la app funcionando.

Codex conserva plantillas, CSS, JS de interfaz, diseño y arquitectura funcional. Tú conservas modelos, vistas/servicios, API, permisos y despliegue. Acordar los archivos compartidos antes de editarlos; ramas/worktrees separados. Los endpoints nuevos de C6-A son propuestas hasta que documentes los definitivos.

Entrega por bloque cerrado: hash, contrato, pruebas y dependencia concreta. No volver a entregar solo un plan ni dar el módulo por terminado por ocultar el aviso. Una decisión pendiente bloquea su regla o activación particular, no todo el desarrollo. Publica por entregas cuando cumplan revisión, autorización aplicable y continuidad, con respaldo y recuperación que preserven operaciones posteriores.
