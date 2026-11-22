REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'EMPTY_CAP_FILE':'上限依据为空', 'BLANK_CAP_FILE':'上限依据全空行', 'BAD_CAP_ENCODING':'上限依据编码无法识别',
    'BAD_CAP_HEADER':'上限依据表头不匹配', 'BROKEN_CAP_CSV':'上限依据CSV损坏', 'NO_VALID_CAP':'上限依据无有效窗口',
    'CAP_MISSING_ID':'上限窗口编号缺失', 'CAP_UNKNOWN_DEVICE':'上限设备不在台账', 'CAP_INVALID_RANGE':'上限窗口时间无效',
    'CAP_NON_POSITIVE':'上限须为正数', 'CAP_ABOVE_RATING':'上限高于设备额定容量', 'CAP_OVERLAP':'上限时间窗重叠',
    'CAP_COLUMN_COUNT':'上限依据列数错误', 'BASIS_NOT_FOUND':'上限依据不存在', 'BAD_BASIS':'上限依据编号无效',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
