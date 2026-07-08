#!/bin/bash

cd ../middleware
cp -pr $1/release/bin/* ../middleware/tcl/tvos/bin/

cp -pr $1/release/lib/* ../middleware/tcl/tvos/lib/
rm -rf $1/release/tvos/lib/*hbbtv*.so
rm -rf $1/release/tvos/lib/libsitatv.so

cp -pr $1/release/jar/* ../middleware/tcl/tvmanager/
rm -rf $1/release/tvmanager/*hbbtv*.jar
cp -p $1/release/lib/libcom_tcl_tv_jni.so ../middleware/tcl/tvmanager/
cp -p $1/release/lib/libsitatv.so ../middleware/tcl/tvmanager/

cp -p $1/release/lib/libhbbtv-server.so ../middleware/tcl/hbbtv/lib/
cp -p $1/release/lib/libhbbtv_plugin.so ../middleware/tcl/hbbtv/lib/plugin/
cp -p $1/release/lib/libcom_tcl_hbbtv_jni.tcl.so ../middleware/tcl/hbbtv/lib/
cp -p $1/release/lib/libalexa.so ../middleware/tcl/alexa/lib/
cp -p $1/release/lib/libAlexaJni.so ../middleware/tcl/alexa/lib/
cp -p $1/release/jar/com.tcl.hbbtv.jar ../middleware/tcl/hbbtv/framework/

#copy apk

cp -pr $1/release/res/hbbtv_config/* ../middleware/tcl/hbbtv/etc/hbbtv/	
cp -pr $1/release/app/* ../middleware/tcl/am_apps/
cp -pr $1/release/res/rtk2851/hbbtv_config/* ../middleware/tcl/hbbtv/etc/hbbtv/
cp -pr $1/release/res/rtk2851/crt ../middleware/tcl/persist/
cp -pr $1/release/res/rtk2851/ua ../middleware/tcl/persist/	
cp -pr $1/release/res/rtk2851/etc ../middleware/tcl/tvos/	
cp -pr $1/tbrowser2/libs/* ../middleware/tcl/tbrowser2/lib/
cp -pr $1/tbrowser2/res/* ../middleware/tcl/tbrowser2/etc/tbrowser2/
cp -pr $1/tbrowser2/jar/* ../middleware/tcl/tbrowser2/framework/
rm -rf $1/tbrowser2/framework/tbrowser.jar
cp -p $1/tbrowser2/libjsext_tutil.so ../middleware/tcl/tbrowser2/lib/

cp -pr $1/AlexaService/* ../middleware/tcl/alexa/lib/
cp -pr $1/OPTEE/libCiPlusCCECP.so ../middleware/tcl/tvos/lib
cp -pr $1/OPTEE/libCiplusTA.a ../middleware/tcl/optee/ci_ecp
cp -pr $1/OPTEE/res/* ../middleware/tcl/optee/ci_ecp/res

cp -pr $1/release/lib/libCiPlusCCECP.so ../middleware/tcl/tvos/lib
cp -pr $1/release/tee/rtk2851m/ci_ecp/libCiplusTA.a ../middleware/tcl/optee/ci_ecp
cp -pr $1/release/tee/rtk2851m/ci_ecp/res/* ../middleware/tcl/optee/ci_ecp/res

cp -p $1/release/Bsp_info.txt ../middleware/tcl/tvos/Bsp_info.txt
cp -p $1/release/fpp_info.txt ../middleware/tcl/tvos/fpp_info.txt
cp -p $1/release/tbrowser2.0_info.txt ../middleware/tcl/tbrowser2/tbrowser2.0_info.txt
cp -p $1/release/svninfo.txt ../middleware/tcl/svninfo.txt


cp -p $1/fpp/libfpp.so ../middleware/tcl/tvos/lib/
cp -p $1/fpp/libtcl_memc.so ../middleware/tcl/tvmanager/

cp -p $1/webview/TCLWebView.apk ../middleware/tcl/webview/
cp -p $1/webview/twebview.jar ../middleware/tcl/webview/


