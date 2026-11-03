from .jobstreet import JobStreetAdapter
from .linkedin import LinkedInAdapter
from .glints import GlintsAdapter
from .indeed import IndeedAdapter
from .dealls import DeallsAdapter
from .kalibrr import KalibrrAdapter
from .techinasia import TechInAsiaAdapter

ADAPTERS = {'linkedin': LinkedInAdapter, 'jobstreet': JobStreetAdapter,
            'glints': GlintsAdapter, 'indeed': IndeedAdapter,
            'dealls': DeallsAdapter, 'kalibrr': KalibrrAdapter, 'techinasia': TechInAsiaAdapter}
