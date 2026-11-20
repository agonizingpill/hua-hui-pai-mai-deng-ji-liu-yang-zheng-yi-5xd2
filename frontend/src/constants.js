export const ROLES={operator:'场内验级员',supervisor:'拍卖主管',viewer:'观察席'};
export const GRADES=['A','B','C'];
export const SAMPLE_STATES={recorded:'待估级',queued:'排队',running:'计算中',ready:'待主管核级',approved:'已核级',failed:'估级失败'};
export const LOT_STATES={offered:'挂场',sold:'已成交',cancelled:'已撤下'};
export const EXPERIMENT_STATES={running:'进行中',finalized:'已定稿'};
export const ARMS={treatment:'新液',control:'清水'};
export const pairState=p=>p.status==='void'?'已作废':p.role==='backup'?(p.status==='active'?'候补已启用':'候补中'):'正选进行中';
