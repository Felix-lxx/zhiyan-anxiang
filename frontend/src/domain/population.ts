export interface PopulationProfile {
  mobility_count:number;direct_contact_count:number;sleeping_count:number
  awake_preparation_seconds:number;sleeping_preparation_seconds:number
  walking_speed:number;mobility_walking_speed:number
}

export function defaultPopulationProfile(total:number):PopulationProfile {
  const n=Math.max(1,Math.floor(total||1))
  return {mobility_count:1,direct_contact_count:Math.max(1,Math.floor(n/5)),sleeping_count:Math.max(1,Math.floor(n/3)),
    awake_preparation_seconds:8,sleeping_preparation_seconds:25,walking_speed:1.25,mobility_walking_speed:.65}
}

export function populationIssue(value:PopulationProfile|null,total:number):string {
  if(!value)return ''
  for(const key of ['mobility_count','direct_contact_count','sleeping_count'] as const){
    if(!Number.isInteger(value[key])||value[key]<0||value[key]>total)return '每项需求人数须为0至参演总人数之间的整数，三项允许重叠。'
  }
  if(!Number.isInteger(value.awake_preparation_seconds)||value.awake_preparation_seconds<0||value.awake_preparation_seconds>120
    ||!Number.isInteger(value.sleeping_preparation_seconds)||value.sleeping_preparation_seconds<0||value.sleeping_preparation_seconds>180)return '准备时间须为有效整数：清醒0–120秒，熟睡0–180秒。'
  if(value.sleeping_preparation_seconds<value.awake_preparation_seconds)return '熟睡准备时间不能短于清醒准备时间。'
  if(!Number.isFinite(value.walking_speed)||value.walking_speed<.8||value.walking_speed>1.8
    ||!Number.isFinite(value.mobility_walking_speed)||value.mobility_walking_speed<.3||value.mobility_walking_speed>1.2)return '请核对基础步速：自主行动0.8–1.8，需协助行动0.3–1.2米/秒。'
  return value.mobility_walking_speed>value.walking_speed?'需协助行动的基础步速不能高于自主行动步速。':''
}
