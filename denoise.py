from enum import Enum
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

FILLER_PATTERNS = [
    re.compile(r'^(你好|您好|hi|hello)[，,！!。.\s]*', re.IGNORECASE),
    re.compile(r'请问(一下|您)?'),
    re.compile(r'能不能帮我(一下)?'),
    re.compile(r'麻烦(你|您)(帮我)?'),
    re.compile(r'谢谢(你|您)?(了)?'),
    re.compile(r'其实我(是)?想'),
    re.compile(r'我想问(一下)?'),
    re.compile(r'作为\s*(一个)?\s*(chatgpt|gpt|大模型|人工智能|ai助手)', re.IGNORECASE),
    re.compile(r'请(你)?务必(认真|仔细)?'),
    re.compile(r'请一步步思考'),
    re.compile(r"let'?s think step by step", re.IGNORECASE),
    re.compile(r'please (be careful|think step by step|act as .*?)\.?', re.IGNORECASE),
]

SIGNATURE_RE = re.compile(r'(\n-- \n|\nbest regards\b|\n此致\s*\n敬礼)', re.IGNORECASE)

OPEN_TO_CLOSE_PUNCTUATION = {
    "'": "'",
    '"': '"',
    '“': '”',
    '‘': '’',
    '《': '》',
}

# jieba / ICTCLAS 词性标记 → 中文名称
POS_FLAG_ZH = {
    'n': '名词',
    'nr': '人名',
    'nr1': '汉语姓氏',
    'nr2': '汉语名字',
    'nrj': '日语人名',
    'nrf': '音译人名',
    'ns': '地名',
    'nsf': '音译地名',
    'nt': '机构团体',
    'nz': '其他专名',
    'nl': '名词性惯用语',
    'ng': '名词性语素',
    'nw': '作品名',
    't': '时间词',
    'tg': '时间词性语素',
    's': '处所词',
    'f': '方位词',
    'v': '动词',
    'vd': '副动词',
    'vn': '名动词',
    'vshi': '动词是',
    'vyou': '动词有',
    'vf': '趋向动词',
    'vx': '形式动词',
    'vi': '不及物动词',
    'vl': '动词性惯用语',
    'vg': '动词性语素',
    'a': '形容词',
    'ad': '副形词',
    'an': '名形词',
    'ag': '形容词性语素',
    'al': '形容词性惯用语',
    'b': '区别词',
    'bl': '区别词性惯用语',
    'z': '状态词',
    'r': '代词',
    'rr': '人称代词',
    'rz': '指示代词',
    'rzt': '时间指示代词',
    'rzs': '处所指示代词',
    'rzv': '谓词性指示代词',
    'ry': '疑问代词',
    'ryt': '时间疑问代词',
    'rys': '处所疑问代词',
    'ryv': '谓词性疑问代词',
    'rg': '代词性语素',
    'm': '数词',
    'mq': '数量词',
    'q': '量词',
    'qv': '动量词',
    'qt': '时量词',
    'd': '副词',
    'dg': '副词性语素',
    'dl': '副词性惯用语',
    'p': '介词',
    'pba': '介词把',
    'pbei': '介词被',
    'c': '连词',
    'cc': '并列连词',
    'u': '助词',
    'uzhe': '着',
    'ule': '了',
    'uguo': '过',
    'ude1': '的',
    'ude2': '地',
    'ude3': '得',
    'usuo': '所',
    'udeng': '等',
    'uyy': '一样',
    'udh': '的话',
    'uls': '来讲',
    'uzhi': '之',
    'ulian': '连',
    'e': '叹词',
    'y': '语气词',
    'o': '拟声词',
    'h': '前缀',
    'k': '后缀',
    'x': '字符串',
    'xx': '非语素字',
    'xu': '网址',
    'w': '标点符号',
    'wkz': '左括号',
    'wky': '右括号',
    'wyz': '左引号',
    'wyy': '右引号',
    'wj': '句号',
    'ww': '问号',
    'wt': '叹号',
    'wd': '逗号',
    'wf': '分号',
    'wn': '顿号',
    'wm': '冒号',
    'ws': '省略号',
    'wp': '破折号',
    'wb': '百分号千分号',
    'wh': '单位符号',
    'eng': '英文',
    'i': '成语',
    'j': '简称略语',
    'l': '习用语',
}

class Context(Enum):
    NOUN = 0
    EMPHASIZE = 1      # 强调
    COMMAND = 2        # 命令
    

def is_punctuation(word):
    if not word:
        return False
    return all(unicodedata.category(ch).startswith('P') for ch in word)


def flag_to_zh(flag, word=''):
    # jieba 常把 。，！？ 等标成 x（字符串），这里按字符纠正为标点
    if is_punctuation(word):
        return '标点符号'
    if flag in POS_FLAG_ZH:
        return POS_FLAG_ZH[flag]
    for size in range(len(flag) - 1, 0, -1):
        prefix = flag[:size]
        if prefix in POS_FLAG_ZH:
            return POS_FLAG_ZH[prefix]
    return flag


def denoise(text):
    if not text:
        return ''
    next_text = str(text).replace('\r\n', '\n')
    next_text = strip_signature(next_text)
    next_text = re.sub(r'[ \t\u00a0\u3000]+', ' ', next_text)
    next_text = re.sub(r'\n{3,}', '\n\n', next_text)
    for pattern in FILLER_PATTERNS:
        next_text = pattern.sub('', next_text)
    next_text = tidy_punctuation(next_text)
    next_text = collapse_duplicate_lines(next_text)
    next_text = collapse_repeated_sentences(next_text)
    next_text = re.sub(r'[！!]{2,}', '！', next_text)
    next_text = re.sub(r'[。.]{3,}', '…', next_text)
    return next_text.strip()

class SimplifySentence:
    def __init__(self, text):
        self.text = text
        self.tokens = []
        self.position = 0
        self.context = None
        self.nouns = [-1, -1, -1]  # 保留最近的3个名词
        self.prevSentenceEnd = -1
        self.prevPrevSentenceEnd = -1

    def simplify(self):
        import jieba.posseg as pseg
        self.tokens = [[word, flag_to_zh(flag, word)] for word, flag in pseg.cut(str(self.text))]
        size = len(self.tokens)
        while self.position < size:
            token = self.tokens[self.position]
            if token[1] == '名词':
                self.simplify_noun()
            elif token[1] in ['形容词', '副形词']:
                self.simplify_adjective()
            elif token[1] in ['动词', '名动词']:
                self.simplify_verb()
            elif token[1] == '副词':
                self.simplify_adverb()
            elif token[1] == '介词':
                self.simplify_preposition()
            elif token[1] == '连词':
                self.simplify_conjunction()
            elif token[1] == '数词':
                self.simplify_number()
            elif token[1] == '方位词':
                self.simplify_direction()
            elif token[1] == '标点符号':
                self.simplify_punctuation()
            self.position += 1
        return ''.join([token[0] for token in self.tokens])

    def simplify_noun(self):
        curToken = self.tokens[self.position]
        if curToken[0] == '业务':
            if self.tokens[self.position + 1][1] == '名词':
                curToken[0] = ''
        # 把tokens数组中在position之后的名词都合并到当前，并删除后面的名词

        mergeNouns = []
        for i in range(self.position + 1, len(self.tokens)):
            if self.tokens[i][1] == '名词':
                mergeNouns.append(i)
            else:
                break
        if mergeNouns:
            curToken[0] = ''.join([self.tokens[i][0] for i in mergeNouns])
            for i in mergeNouns:
                self.tokens[i][0] = ''
        # 从后往前查找下nouns中是否存在当前名词，如果存在，则删除当前名词，不影响语义
        sameIndex = -1
        for i in range(2, -1, -1):
            if self.nouns[i] != -1 and self.tokens[self.nouns[i]][0] == self.tokens[self.position][0]:
                sameIndex = i
                break
        # 查找下nouns中是否存在当前名词，如果存在，则删除当前名词，不影响语义
        if sameIndex == 2:
            # 不同句子中
            if self.prevSentenceEnd > self.nouns[2]:
                curToken[0] = ''
        elif sameIndex == 1:
            # 同一个句子中
            if self.prevSentenceEnd < self.nouns[0]:        
                self.duplicateSameNounInOneSentence()
                

        if curToken[0] != '':
            self.nouns[0] = self.nouns[1]
            self.nouns[1] = self.nouns[2]
            self.nouns[2] = self.position

    def duplicateSameNounInOneSentence(self):
        # 名1的名3或名2的名3=>名1或名2的名3
        firstDeIndex = -1
        secondDeIndex = -1
        conjunctionIndex = -1
        for i in range(self.nouns[0], self.nouns[1] - 1):
            if self.tokens[i][0] == '的':
                firstDeIndex = i
            elif self.tokens[i][0] != '':
                return
        for i in range(self.nouns[1], self.nouns[2] - 1):
            if self.tokens[i][0] in ['或', '和']:
                conjunctionIndex = i
            elif self.tokens[i][0] != '':
                return
        for i in range(self.nouns[2], self.position - 1):
            if self.tokens[i][0] == '的':
                secondDeIndex = i
            elif self.tokens[i][0] != '':
                return
        
        self.tokens[firstDeIndex][0] = ''
        self.tokens[self.nouns[1]][0] = ''

    def simplify_adjective(self):
        curToken = self.tokens[self.position]
        if curToken[0] == '详细':
            if self.tokens[self.position + 1][1] == '名词':
                curToken[0] = ''

    def simplify_verb(self):
        curToken = self.tokens[self.position]
        if curToken[0] == '已有':
            if self.tokens[self.position + 1][0] == '的' and (self.tokens[self.position + 2][0] in ['\'', '\"', '‘', '“', '《'] or self.tokens[self.position + 2][1] == '名词'):
                curToken[0] = ''
                self.tokens[self.position + 1][0] = ''
        elif curToken[0] == '综合' and self.tokens[self.position + 1][1] == '动词':
            curToken[0] = ''
        elif curToken[0] == '用于' and self.tokens[self.position + 1][1] == '动词':
            curToken[0] = '来'
        elif curToken[0] in ['拥有', '具有']:
            curToken[0] = '有'
        elif curToken[0] == '能够':
            curToken[0] = '能'

    def simplify_adverb(self):
        curToken = self.tokens[self.position]
        if curToken[0] in ['经常', '常常']:
            curToken[0] = '常'
        elif curToken[0] in ['非常', '太', '则']:
            curToken[0] = ''
        elif curToken[0] == '不再' and self.tokens[self.position + 1][1] == '动词':
            curToken[0] = '不'
            
    def simplify_preposition(self):
        curToken = self.tokens[self.position]
        if curToken[0] in ['通过', '使用']:
           curToken[0] = '用'
        

    def simplify_number(self):
        curToken = self.tokens[self.position]
        if self.context != Context.EMPHASIZE and curToken[0] in ['一个', '一位', '一名']:
            if self.tokens[self.position + 1][1] == '名词':
                curToken[0] = ''
        elif curToken[0] == '十分' and self.tokens[self.position + 1][1] in ['形容词', '副形词']:
            curToken[0] = ''

    def simplify_conjunction(self):
        curToken = self.tokens[self.position]
        if curToken[0] == '所以':
            # 前一分句开头是"因为"
            if (self.tokens[self.prevPrevSentenceEnd + 1][0] == '因'):
                curToken[0] = ''
        elif curToken[0] in ['那么', '则']:
            if (self.tokens[self.prevPrevSentenceEnd + 1][0] == '若'):
                curToken[0] = ''
        
        if curToken[0] in ['并且', '而且']:
            curToken[0] = '且'
        elif curToken[0] in ['或者', '或是']:
            curToken[0] = '或'
        elif curToken[0] in ['但是', '然而', '不过']:
            curToken[0] = '但'
        elif curToken[0] in ['因为', '由于']:
            curToken[0] = '因'
        elif curToken[0] in ['所以', '因此']:
            curToken[0] = '故'
        elif curToken[0] in ['如果', '倘若']:
            curToken[0] = '若'

        if curToken[0] in ['只有', '仅有', '唯有']:
            self.context = Context.EMPHASIZE
        elif curToken[0] in ['与', '和', '且']:
            if (self.tokens[self.position - 1][1] in ['形容词', '副形词'] and self.tokens[self.position + 1][1] in ['形容词', '副形词']):
                curToken[0] = ''
        #相邻2个连词，留字数最少的那个
        if self.tokens[self.position + 1][1] == '连词':
            if len(curToken[0]) > len(self.tokens[self.position + 1][0]):
                curToken[0] = ''
            else:
                self.tokens[self.position + 1][0] = ''
                

    def simplify_direction(self):
        curToken = self.tokens[self.position]
        if curToken[0] in ['上面', '以上']:
            if self.tokens[self.position + 1][1] == '数词':
                self.tokens[self.position + 1][0] = ''
                if self.tokens[self.position + 2][1] == '数词':
                    self.tokens[self.position + 2][0] = ''

    def simplify_punctuation(self):
        curToken = self.tokens[self.position]
        if self.is_sentence_end_punctuation(curToken[0]):
            self.prevPrevSentenceEnd = self.prevSentenceEnd
            self.prevSentenceEnd = self.position
            self.context = Context.NOUN

        closer = OPEN_TO_CLOSE_PUNCTUATION.get(curToken[0])
        if closer:
            for i in range(self.position + 1, len(self.tokens)):
                if self.tokens[i][0] == closer:
                    self.position = i
                    break
    
    def is_sentence_end_punctuation(self, value):
        return value in [',', '.', '，', '。', '!', '?', '！', '？', ';', '；']

def tidy_punctuation(text):
    text = re.sub(r'^[，,。. \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[，,]{2,}', '，', text)
    text = re.sub(r'[。.]{2,}', '。', text)
    text = re.sub(r'[，,]\s*[，,]', '，', text)
    text = re.sub(r'[，,]\s*([。！？])', r'\1', text)
    return text


def collapse_duplicate_lines(text):
    seen = set()
    lines = []
    for line in text.split('\n'):
        norm = line.strip()
        if not norm:
            if lines and lines[-1] != '':
                lines.append('')
            continue
        if norm in seen:
            continue
        seen.add(norm)
        lines.append(line.rstrip())
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))


def strip_signature(text):
    match = SIGNATURE_RE.search(text)
    if match and match.start() > 40:
        return text[: match.start()].strip()
    return text


def collapse_repeated_sentences(text):
    parts = re.split(r'(?<=[。！？!?\n])', text)
    out = []
    prev = ''
    for part in parts:
        norm = part.strip()
        if not norm:
            continue
        if norm == prev:
            continue
        out.append(part)
        prev = norm
    return re.sub(r'\n{3,}', '\n\n', ''.join(out))

def simple_prompt(src_file, dst_file):
    with open(src_file, 'r', encoding='utf-8') as f:
        text = f.read()
    simple_text = denoise(text)
    simplifyer = SimplifySentence(simple_text)
    simple_text = simplifyer.simplify()
    with open(dst_file, 'w', encoding='utf-8') as f:
        f.write(simple_text)

if __name__ == '__main__':
    import sys

    if len(sys.argv) != 3:
        print('用法: python simplePrompt.py <提示词文件路径> <简化后输出路径>')
        exit(1)
    simple_prompt(sys.argv[1], sys.argv[2])
    print('简化完成:', sys.argv[2])
