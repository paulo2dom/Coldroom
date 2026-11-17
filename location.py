"""Localizacao do equipamento (pais/zona/loja/local/equipamento), lida do config.py.
Usado pelo main.py (Pico) e pelo desktop/preview.py (PC).
"""
LEVELS = ('pais', 'zona', 'loja', 'local', 'equipamento')
_FIELDS = {
    'pais': ('LOCATION_COUNTRY', 'pt'),
    'zona': ('LOCATION_ZONE', 'zona'),
    'loja': ('LOCATION_STORE', 'loja'),
    'local': ('LOCATION_AREA', 'local'),
    'equipamento': ('LOCATION_EQUIPMENT', 'cf-01'),
}


def slug(value):
    # Nivel de topico MQTT: minusculas, sem espacos nem caracteres reservados
    value = str(value).strip().lower().replace(' ', '-')
    for ch in '/#+':
        value = value.replace(ch, '-')
    return value or 'desconhecido'


def load(config):
    """Devolve (dict da localizacao, topico base 'pais/zona/loja/local/equipamento')."""
    loc = {}
    for key in LEVELS:
        field, default = _FIELDS[key]
        loc[key] = slug(getattr(config, field, default))
    # Ordem explicita; um dict nao garante ordem em MicroPython
    return loc, '/'.join(loc[k] for k in LEVELS)
