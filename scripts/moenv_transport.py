import json,socket,ssl
from http.client import IncompleteRead
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,build_opener
from download_moenv import NoRedirect,records
from download_moenv_checkpoint import SafeError
class TransportError(SafeError):
    def __init__(self,category,phase,http_status=None,retryable=False,retry_after=None):
        self.diagnostic={'category':category,'phase':phase,'http_status':http_status,'retryable':retryable,'retry_after_seconds':retry_after}
        super().__init__(category+'_'+phase+('_'+str(http_status) if http_status is not None else ''))
def network_error(reason,phase):
    if isinstance(reason,ssl.SSLCertVerificationError):return TransportError('tls_certificate_error',phase)
    if isinstance(reason,ssl.SSLError):return TransportError('tls_error',phase)
    if isinstance(reason,socket.gaierror):return TransportError('dns_error',phase,retryable=reason.errno==socket.EAI_AGAIN)
    if isinstance(reason,TimeoutError):return TransportError('timeout',phase,retryable=True)
    if isinstance(reason,(ConnectionError,IncompleteRead)):return TransportError('connection_or_incomplete_response',phase,retryable=True)
    return TransportError('network_error',phase,retryable=True)
def fetch(dataset,offset,key):
    if not key:raise SafeError('missing_secret')
    url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode({'api_key':key,'format':'json','offset':offset,'limit':1000})
    phase='open'
    try:
        with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=45) as response:
            phase='read';data=response.read(20000001)
    except HTTPError as error:
        raw=(error.headers.get('Retry-After','') if error.headers else '').strip()
        after=int(raw) if raw and raw.isascii() and raw.isdigit() and len(raw)<=6 else None
        retryable=error.code in (500,502,503,504) and (after is None or after<=300)
        raise TransportError('http_error',phase,error.code,retryable,after) from None
    except URLError as error:raise network_error(error.reason,phase) from None
    except (OSError,IncompleteRead) as error:raise network_error(error,phase) from None
    except Exception:raise TransportError('unexpected_transport_error',phase) from None
    if len(data)>20000000:raise SafeError('response_too_large')
    try:return records(json.loads(data.decode('utf-8-sig')))
    except Exception:raise SafeError('invalid_response_layout') from None
