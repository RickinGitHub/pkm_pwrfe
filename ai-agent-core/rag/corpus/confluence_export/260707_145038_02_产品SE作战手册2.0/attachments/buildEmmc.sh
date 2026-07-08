#!/bin/bash

version=$1
area=$2
emmcSize=$3
projectId=$4
MODEL1=$5

 #获取android根目录
function get_android_top(){
    local BUILD_SH_REAL_DIR=$(dirname $(readlink -f $0))
    local TOPFILE=build/make/core/envsetup.mk
    local HERE=$PWD
    local T=$HERE
    cd $BUILD_SH_REAL_DIR
    while [ \( ! \( -f $TOPFILE \) \) -a \( $PWD != "/" \) ]; do
        \cd ..
        T=`PWD= /bin/pwd -P`
    done
    \cd $HERE
    if [ -f "$T/$TOPFILE" ]; then
        echo $T
    fi
}

ANDROID_PATH=$(get_android_top)
IMGPATH=out/target/product/tcl9618_osv/images
CURRENT_PATH=`pwd`
SRC_PATH_FREQ='vendor/tcl/sita/tclconfig_gl/software/param/defaultDB/preset_channel'

# 制作emmcini文件
function emmcini(){
    cd $CURRENT_PATH
    echo mboot_a 0xA00000 >block.txt
    echo mboot_b 0xA00000 >>block.txt
    echo uenv 0x1000000 >>block.txt
    echo uuenv 0x1000000 >>block.txt
    cat $ANDROID_PATH/$IMGPATH/scripts/set_partition|grep = |awk '{print $5}'|awk -F ',' '{print $1,$2}'|awk -F '=' '{print $1,$2,$3,$4}'|awk '{print $2,$4}'|awk '{print $1,$2}'>>block.txt
    #32G
    if [[ "$emmcSize" == "32" ]];then
        #echo userdata 0x108500000 >> block.txt
        echo userdata 0x5546FA000 >>block.txt
    fi
    if [[ "$emmcSize" == "64" ]];then
        echo userdata 0xC990FA000 >>block.txt
    fi
    rm -rf emmcbin.ini
    id=1
    while read -r line;do
        name=`echo $line | awk '{print $1}'`
        size=`echo $line | awk '{print $2}'`
        img=`echo $ANDROID_PATH\/$IMGPATH\/$name.img`
        echo -e "[$name-volume]\nimage=$img\nvol_id=$id\nvol_size=$size\nvol_name=$name" >> emmcbin.ini
        id=`expr $id + 1`
    done < block.txt
}

# 修改emmcini配置文件
function fixini(){
    cd $CURRENT_PATH
    sed -i 's/_a.img/.img/g' emmcbin.ini
    sed -i 's/_b.img/.img/g' emmcbin.ini
    sed -i 's/mboot.img/mboot.bin/g' emmcbin.ini
    sed -i 's/cache.img/cache.img.raw/g' emmcbin.ini
    sed -i 's/\/userdata.img/\/userdata.img.raw/g' emmcbin.ini
    sed -i 's/super.img/super.img.raw/g' emmcbin.ini
    sed -i "s#${ANDROID_PATH}/${IMGPATH}/misc.img##g" emmcbin.ini
    sed -i "s#${ANDROID_PATH}/${IMGPATH}/tcllog.img##g" emmcbin.ini
}

# unsparse 转换
function setraw(){
    cd $CURRENT_PATH
    cp -rf uenv.img $ANDROID_PATH/$IMGPATH && sync
    cp -rf uuenv.img $ANDROID_PATH/$IMGPATH && sync
    cp -rf factory.img $ANDROID_PATH/$IMGPATH && sync
    cp -rf $ANDROID_PATH/$IMGPATH/../super.img $ANDROID_PATH/$IMGPATH/
    $ANDROID_PATH/out/host/linux-x86/bin/simg2img $ANDROID_PATH/$IMGPATH/super.img $ANDROID_PATH/$IMGPATH/super.img.raw
    $ANDROID_PATH/out/host/linux-x86/bin/simg2img $ANDROID_PATH/$IMGPATH/userdata.img $ANDROID_PATH/$IMGPATH/userdata.img.raw
    $ANDROID_PATH/out/host/linux-x86/bin/simg2img $ANDROID_PATH/$IMGPATH/cache.img $ANDROID_PATH/$IMGPATH/cache.img.raw
}
# 制作emmc.bin文件
function makesoft(){
    cd $CURRENT_PATH
    chmod a+x emmcnize
    # 加密fde软件带参数-e
    #./emmcnize emmcbin.ini emmc.bin -a1 -g  -e  SWFDEKey_TCL_2022_MT9653_AOSP_CN.bin
    # 未加密软件 不需要带-e参数
    ./emmcnize emmcbin.ini emmc.bin -a1 -g
}

#切割并制作脚本文件
function emmcOutput(){
    cd $CURRENT_PATH
    if [ -d emmcOutput ];then
        rm -rf emmcOutput
    fi
     mkdir emmcOutput
     split -b 256M -a 3 -d --additional-suffix=.bin ./emmc.bin "emmcOutput/emmc"
     cd emmcOutput
     echo -e "mmc erase 0 0x4000000\n" >../usb_upgrade_emmc.txt
     over=0
     sum=0
     for i in $(ls)
     do
         sizeE=`ls -l $i | awk '{print $5/512}'`
         emmcsize=`printf "%x" $sizeE`
         echo "fatload usb 0 0x30200000 $i \$size" >> ../usb_upgrade_emmc.txt
         echo "mmc write 0x30200000 0x$sum 0x$emmcsize" >> ../usb_upgrade_emmc.txt
         over1=`ls -l $i | awk '{print $5}'`
         over=$(($over+$over1))
         sum=`printf "%x" $(($over/512))`
     done

     #抄写rom_emmc_boot.bin
     echo -e "\nfatload usb 0 0x30200000 rom_emmc_boot.bin" >> ../usb_upgrade_emmc.txt
     echo -e "partition write.boot mmc 0 1 0x30200000 \${filesize}" >> ../usb_upgrade_emmc.txt
     echo -e "partition write.boot mmc 0 2 0x30200000 \${filesize}" >> ../usb_upgrade_emmc.txt
     cp -rf $ANDROID_PATH/$IMGPATH/rom_emmc_boot.bin $CURRENT_PATH/emmcOutput && sync

     echo -e "\nreset" >> ../usb_upgrade_emmc.txt
     cd -
     cp -rf usb_upgrade_emmc.txt emmcOutput
     rm -rf usb_upgrade_emmc.txt
}


#制作上传产物
function output(){
    cd $CURRENT_PATH
    if [ -d output ];then
         rm -rf output
    fi
    mkdir -p output
    time=`date '+%Y%m%d'`
    cp -rf $ANDROID_PATH/$IMGPATH/rom_emmc_boot.bin output
    cp -rf $ANDROID_PATH/$IMGPATH/rom_emmc_boot.bin output/rom_emmc_boot2.bin
    cp -rf emmcOutput/usb_upgrade_emmc.txt output
    tar -czvf output/mt9653_GL_U_YCX_PID${projectId}_${version}_${emmcSize}G_${time}_${MODEL1}.tar.gz emmc.bin
    md5sum emmc.bin >output/mt9653_GL_U_YCX_PID${projectId}_${version}_${emmcSize}G_${MODEL1}_${time}_MD5.txt
    cd output
    md5sum rom_emmc_boot.bin >> mt9653_GL_U_YCX_PID${projectId}_${version}_${emmcSize}G_${MODEL1}_${time}_MD5.txt
    md5sum rom_emmc_boot2.bin >> mt9653_GL_U_YCX_PID${projectId}_${version}_${emmcSize}G_${MODEL1}_${time}_MD5.txt
    if [ $? -eq 0  ];then
        echo -e "\033[32m=========== make output file success. ==================\033[0m"
    else
        echo -e "\033[31m=========== make output file failed, pls check. ========\033[0m"
        exit 1
    fi

    
}
#编译预抄写
function buildemmc(){
    emmcini
    fixini
    setraw
    makesoft
    emmcOutput
    output
    # 恢复预抄写前软件状态
    
    echo -e "========================== emmc make done! ====================================="
}


#设置数据库默认属性
function set_param_for_flash_write_database () {
    cd $CURRENT_PATH
    chmod 777 flash_write_script/bin/sqlite3
    ./flash_write_script/bin/sqlite3 $ANDROID_PATH/vendor/tcl/sita/userdata/userPQ.db << EOF
    update TvDisplaySettingTbl set bAutoFormat=0;
    update IndistinguishablePicmodeTbl set lightsensor=0;
    update PicModeParamTbl SET i8Contrast=100 WHERE enCodecType=3 and enPicModeType=0;
    update PicModeParamTbl SET i8Contrast=96 WHERE enCodecType=15 and enPicModeType=0;
    update PicModeParamTbl SET i8Contrast=96 WHERE enCodecType=16 and enPicModeType=0;
    update PicModeParamTbl SET i8Contrast=96 WHERE enCodecType=17 and enPicModeType=0;
    update PicModeParamTbl SET i8Contrast=96 WHERE enCodecType=18 and enPicModeType=0;
    update PicModeParamTbl SET i8Contrast=92 WHERE enCodecType=21 and enPicModeType=0;
    update PicModeParamTbl SET i8Saturation=60 WHERE enPicModeType=0;
    select * from TvDisplaySettingTbl;
.quit
EOF
}

function setLNB(){
    cd $CURRENT_PATH
    chmod 777 flash_write_script/bin/sqlite3
    ./flash_write_script/bin/sqlite3 $ANDROID_PATH/vendor/tcl/sita/userdata/DtvData.db << EOF
    UPDATE DtvSettingTbl SET SettingValue = x'01' WHERE SettingKey = 'lnbstatus';
.quit
EOF

}

#编译前
function prebuild(){

    #预抄写预置条件
    cd $ANDROID_PATH/vendor/tcl/sita
    if [ -d userdata ];then
         rm -rf userdata
    fi
    mkdir userdata&&cd userdata
    cp -rf $ANDROID_PATH/vendor/tcl/tvcust/aio_resources/resource/common/database/main_pq_def.db ./userPQ.db
    if [ "$area" == "EU" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/EU_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/EU_DtvData_HZ.db ./DtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/satellite_EU.db ./satellite.db
    fi
    if [ "$area" == "NA" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/NA_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/NA_AtscData_HZ.db ./AtscData.db
    fi
    if [ "$area" == "AP" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/AP_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/AP_DtvData_HZ.db ./DtvData.db
    fi
    if [ "$area" == "AU" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/AU_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/AU_DtvData_HZ.db ./DtvData.db
    fi
    if [ "$area" == "CA" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/CA_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/CA_AtscData_HZ.db ./AtscData.db
    fi
    if [ "$area" == "LA" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/LA_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/LA_DtvData_HZ.db ./DtvData.db
    fi
    if [ "$area" == "HK" ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/DTMB_AtvData_HZ.db ./AtvData.db
        cp $ANDROID_PATH/$SRC_PATH_FREQ/DTMB_DtvData_HZ.db ./DtvData.db
    fi
    if [ "$area" == "JP"  ];then
        cp $ANDROID_PATH/$SRC_PATH_FREQ/JP_DtvData_HZ.db ./DtvData.db
    fi
    if [ $? -eq 0  ];then
        echo -e "\033[32m=========== copy file success. ===============\033[0m"
    else
        echo -e "\033[31m=========== the option is wrong.Please make sure it.options: EU NA AP AU CA LA. ========\033[0m"
        exit 1
    fi
    #修改PID
    pid=`printf %x $projectId`
    echo "$pid"
    pidLength=`echo ${#pid}`
    len=5
    if [ -f "$ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/project_id_high.bin" ];then
        echo -e -n "\x0\x0" > $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/project_id_high.bin
    fi
    if [ "$pidLength" -lt "$len" ];then
        if [ $pidLength == "1"  ];then
            pid=`echo 000$pid`
        fi
        if [ $pidLength == "2"  ];then
            pid=`echo 00$pid`
        fi
        if [ $pidLength == "3"  ];then
            pid=`echo 0$pid`
        fi
        sid=${pid:0:2}
        hid=${pid:2:4}
        echo "sid is :$sid "
        echo "hid is :$hid "
        echo -e -n "\x${hid}\x${sid}" > $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/project_id.bin
    else
        if [ $pidLength == "5"  ];then
            pid=`echo 000$pid`
        fi
        if [ $pidLength == "6"  ];then
            pid=`echo 00$pid`
        fi
        if [ $pidLength == "7"  ];then
            pid=`echo 0$pid`
        fi
        lpid=${pid:4:8}
        hpid=${pid:0:4}
        lsid=${lpid:0:2}
        lhid=${lpid:2:4}
        hsid=${hpid:0:2}
        hhid=${hpid:2:4}
        echo "lsid is: "$lsid
        echo "lhid is: "$lhid
        echo "hsid is: "$hsid
        echo "hhid is: "$hhid
        echo -e -n "\x${lhid}\x${lsid}" > $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/project_id.bin
        echo -e -n "\x${hsid}\x${hhid}" > $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/project_id_high.bin
    fi
    touch $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/preset_img
    chmod 660 $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/preset_img
    ls -l $ANDROID_PATH/vendor/tcl/non_ssi/vendor/mt9653_gl_s2u/impdata/preset_img
    set_param_for_flash_write_database
    if [ "$area" == "JP"  ];then
        setLNB
    fi
    if [ $? -eq 0  ];then
        echo -e "\033[32m=========== set PID ${projectId} success. ===============\033[0m"
    else
        echo -e "\033[31m=========== set PID ${projectId} failed, pls check. ========\033[0m"
        exit 1
    fi

}
# 编译
function build(){

    #设置版本号
    version=${CURRENT_NPI_VERSION:14:4}
    sed -i  "s/TCL_BUILD_ID.*/TCL_BUILD_ID=V8-T653T01-LF1$version/g"  $ANDROID_HOME_DIR/vendor/tcl/build/script/vendorsetup.sh

    #设置userdata大小
    if [[ "$emmcSize" == "32"  ]];then
        cd $ANDROID_PATH/vendor/mediatek/common-tv/products
        sed -i "s/?= 4434427904 #0x108500000/?= 22891438080 #0x5546FA000/g" BoardConfigCommon_osv.mk
    fi
    if [[ "$emmcSize" == "64"  ]];then
        cd $ANDROID_PATH/vendor/mediatek/common-tv/products
        sed -i "s/?= 4434427904 #0x108500000/?= 54107545600 #0xC990FA000/g" BoardConfigCommon_osv.mk
    fi

    #编译软件
    cd $ANDROID_PATH
    ./tcl_build.sh -p tcl9618_osv-MT9653_GL_S2U_OVERSEA_base-user -j24
    if [ $? -eq 0   ];then
        echo -e "\033[32m=========== build successful. ===============\033[0m"
    else
        echo -e "\033[31m=========== build failed, pls check. ========\033[0m"
        exit 1
    fi

}

prebuild
build
buildemmc
