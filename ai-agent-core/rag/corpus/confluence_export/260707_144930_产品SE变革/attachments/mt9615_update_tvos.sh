#!/bin/bash

set -e

ANDROID_BUILD_TOP=`pwd`
TVOS_REMOTE_PATH=http://gitlab10.tclking.com/delivery2/tvos/base_mt9615_clang_build.git
TVOS_PATH=""
TARGET_PATH=""

# check cur path is android top
if [ ! -d $ANDROID_BUILD_TOP/frameworks ];then
	echo -e "\033[1merror!please run me from android top path.\n\033[0m"
	exit 0
fi

if [ -d $ANDROID_BUILD_TOP/tvos ];then
	rm -rf $ANDROID_BUILD_TOP/tvos
fi


echo -e "\033[1mget the lastest tvos files from gitlab10.\n\033[0m"
git clone $TVOS_REMOTE_PATH $ANDROID_BUILD_TOP/tvos



TVOS_PATH=$ANDROID_BUILD_TOP/tvos
TARGET_PATH=$ANDROID_BUILD_TOP/vendor/tcl

cd $ANDROID_BUILD_TOP/tvos
if [ "$1" != "" ];then
	echo -e "\033[1mget the $1 version tvos files from gitlab10.\n\033[0m"
	git reset --hard $1
fi
echo `git log -1` >$ANDROID_BUILD_TOP/tvos_info.txt

echo -e "\033[1m TVOS_PATH = $TVOS_PATH \n\033[0m"
echo -e "\033[1m TARGET_PATH = $TARGET_PATH \n\033[0m"

##########################tplayer2.0################################
echo -e "\033[1m Start copy tplayer...\n\033[0m"
cp -rf $TVOS_PATH/release/app/tplayer_pr40/* $TARGET_PATH/am_apps/tplayer/

##########################hbbtv################################
echo -e "\033[1m Start copy hbbtv...\n\033[0m"
cp $TVOS_PATH/release/jar/com.tcl.hbbtv.jar $TARGET_PATH/hbbtv/framework
cp $TVOS_PATH/release/lib/libcom_tcl_hbbtv_jni.tcl.so $TARGET_PATH/hbbtv/lib
cp $TVOS_PATH/release/lib/libhbbtv-server.so $TARGET_PATH/hbbtv/lib
cp $TVOS_PATH/release/lib/libhbbtv_plugin.tcl.so $TARGET_PATH/hbbtv/lib/plugin
cp -rf $TVOS_PATH/release/res/mtk9615/hbbtv_config/* $TARGET_PATH/hbbtv/config
cp -rf $TVOS_PATH/release/res/mtk9615/crt $TARGET_PATH/sita/persist
cp -rf $TVOS_PATH/release/res/mtk9615/ua $TARGET_PATH/sita/persist
cp -rf $TVOS_PATH/release/res/mtk9615/etc $TARGET_PATH/sita/tvos

##########################tvmanager################################
echo -e "\033[1m Start copy tvmanager...\n\033[0m"
cp $TVOS_PATH/release/lib/libcom_tcl_tv_jni.so $TARGET_PATH/tvmanager
cp $TVOS_PATH/release/lib/libsitatv.so $TARGET_PATH/tvmanager
cp $TVOS_PATH/release/jar/tvmanager.jar $TARGET_PATH/tvmanager

##########################sita################################
echo -e "\033[1m Start copy sita...\n\033[0m"
cp $TVOS_PATH/release/bin/* $TARGET_PATH/sita/tvos/bin
cp $TVOS_PATH/release/lib/libdvb.so $TARGET_PATH/sita/tvos/libBionic
cp $TVOS_PATH/release/lib/libatsc.so $TARGET_PATH/sita/tvos/libBionic
cp $TVOS_PATH/release/lib/libisdb.so $TARGET_PATH/sita/tvos/libBionic

#####################appmanager################################
echo -e "\033[1m Start copy appmanager...\n\033[0m"
cp $TVOS_PATH/release/lib/libtaf.so $TARGET_PATH/sita/tvos/libBionic

##########################tbrowser3.0################################
echo -e "\033[1m Start copy tbrowser3.0...\n\033[0m"
cp $TVOS_PATH/tbrowser3.0/apps/TCLWebView.apk $TARGET_PATH/app/TCLWebView
cp $TVOS_PATH/tbrowser3.0/jar/twebview.jar $TARGET_PATH/webview
cp $TVOS_PATH/tbrowser3.0/jar/com.tcl.tbrowser.jar $TARGET_PATH/webview/framework
cp $TVOS_PATH/tbrowser3.0/libs/libtbrowser.so $TARGET_PATH/webview/lib
cp $TVOS_PATH/tbrowser3.0/libs/libcom_tcl_tbrowser_jni.tcl.so $TARGET_PATH/webview/lib

##########################ci_ecp################################
echo -e "\033[1m Start copy ci_ecp...\n\033[0m"
cp $TVOS_PATH/release/lib/libCiPlusCCECP.so $TARGET_PATH/sita/tvos/libBionic
cp $TVOS_PATH/release/tee/mt9615/ci_ecp/libCiplusTA.a $TARGET_PATH/optee/ci_ecp
cp -rf $TVOS_PATH/release/tee/mt9615/ci_ecp/res $TARGET_PATH/optee/ci_ecp

##########################alexa################################
echo -e "\033[1m Start copy alexa...\n\033[0m"
cp $TVOS_PATH/release/app/alexa/libalexa.so $TARGET_PATH/alexa
cp $TVOS_PATH/release/app/alexa/libAlexaJni.so $TARGET_PATH/alexa

echo -e "\033[1m done! \n\033[0m"

:<<kk
repo status $TARGET_PATH/am_apps/tplayer \
$TARGET_PATH/hbbtv \
$TARGET_PATH/tvmanager \
$TARGET_PATH/sita/tvos \
$TARGET_PATH/webview \
$TARGET_PATH/alexa \
$TARGET_PATH/optee

cd $TARGET_PATH/app/TCLWebView
git status .
cd -
kk

