import collections
import re
from ..types.data import *

class parser:
    def __init__(self) -> None:
        pass

    def ParseThreadItem(thread_item):
        Titem = {
        "category": "",
        "engine": "",
        "status": "",
        "title": "",
        "developer": "",
        "version":""
        }

        if(thread_item.upper() in data.Tcategory()):
            Titem['category'] = thread_item.replace('[',"").replace(']',"")
        elif(thread_item.upper() in data.Tengine()):
            Titem['engine'] = thread_item.replace('[',"").replace(']',"")
        elif(thread_item.upper() in data.Tstaus()):
            Titem['status'] = thread_item.replace('[',"").replace(']',"")
        else: # Parse Game Name
            strings = thread_item.split('[')
            Titem['title'] = strings[0].replace('[',"").replace(']',"")
            if len(strings) == 2:
                tmp = re.sub('[\W_]+', '',strings[1].strip().replace('[',"").replace(']',"")).upper()                           
                if(tmp in data.Tversion()): #check if this is version or dev
                     Titem['version'] = strings[1].replace('[',"").replace(']',"")
                else:
                     Titem['developer'] = strings[1].replace('[',"").replace(']',"")
            elif len(strings) == 3:
                 Titem['version'] = strings[1].replace('[',"").replace(']',"")
                 Titem['developer'] = strings[2].replace('[',"").replace(']',"")        

        return Titem