from .jobstreet import JobStreetAdapter
from .linkedin import LinkedInAdapter
from .glints import GlintsAdapter
from .indeed import IndeedAdapter

ADAPTERS = {'linkedin': LinkedInAdapter, 'jobstreet': JobStreetAdapter,
            'glints': GlintsAdapter, 'indeed': IndeedAdapter}
