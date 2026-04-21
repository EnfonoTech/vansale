package com.enfono.vansale.demo;

import android.content.Context;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.print.PageRange;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintDocumentInfo;
import android.print.PrintManager;
import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Native Android print bridge.
 *
 * The Capacitor WebView silently ignores {@code window.print()} from inside
 * a sandboxed iframe, so we fetch the PDF bytes on the web side and hand
 * them to Android's {@link PrintManager}. The system print dialog (preview,
 * copies, orientation, Save-as-PDF, HP/Canon/generic Bluetooth) handles the
 * rest.
 *
 * Invoked from the web as:
 * <pre>
 *   await AndroidPrint.printPdf({ pdfBase64: "...", jobName: "Invoice-ACC-001" });
 * </pre>
 *
 * Resolves when the {@link PrintDocumentAdapter} hands the bytes off to the
 * system print service — not when the user hits Print. That's intentional:
 * our web-side code only needs to know the bridge accepted the doc.
 */
@CapacitorPlugin(name = "AndroidPrint")
public class AndroidPrintPlugin extends Plugin {

    @PluginMethod
    public void printPdf(final PluginCall call) {
        final String pdfBase64 = call.getString("pdfBase64");
        final String jobName = call.getString("jobName", "Document");
        if (pdfBase64 == null || pdfBase64.isEmpty()) {
            call.reject("pdfBase64 is required");
            return;
        }

        final byte[] pdfBytes;
        try {
            pdfBytes = Base64.decode(pdfBase64, Base64.DEFAULT);
        } catch (IllegalArgumentException e) {
            call.reject("Invalid base64 PDF bytes: " + e.getMessage());
            return;
        }

        final File tmpDir = getContext().getCacheDir();
        final File tmpPdf;
        try {
            tmpPdf = File.createTempFile("vansale-print-", ".pdf", tmpDir);
            try (FileOutputStream fos = new FileOutputStream(tmpPdf)) {
                fos.write(pdfBytes);
            }
        } catch (IOException e) {
            call.reject("Could not stage PDF: " + e.getMessage());
            return;
        }

        // PrintManager calls must run on the UI thread.
        getActivity().runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    final PrintManager pm = (PrintManager) getContext()
                            .getSystemService(Context.PRINT_SERVICE);
                    if (pm == null) {
                        call.reject("PrintManager unavailable");
                        tmpPdf.delete();
                        return;
                    }
                    pm.print(
                            jobName,
                            new PdfDocumentAdapter(jobName, tmpPdf),
                            new PrintAttributes.Builder().build()
                    );
                    JSObject ret = new JSObject();
                    ret.put("dispatched", true);
                    call.resolve(ret);
                } catch (Throwable t) {
                    call.reject("Print dispatch failed: " + t.getMessage());
                    tmpPdf.delete();
                }
            }
        });
    }

    /**
     * Minimal PDF-backed PrintDocumentAdapter. Copies the staged file to
     * the target ParcelFileDescriptor supplied by the system print service.
     * Deletes the staged file on finish/cancel.
     */
    private static final class PdfDocumentAdapter extends PrintDocumentAdapter {
        private final String jobName;
        private final File source;

        PdfDocumentAdapter(String jobName, File source) {
            this.jobName = jobName;
            this.source = source;
        }

        @Override
        public void onLayout(PrintAttributes oldAttrs,
                             PrintAttributes newAttrs,
                             CancellationSignal cancellationSignal,
                             LayoutResultCallback callback,
                             Bundle extras) {
            if (cancellationSignal.isCanceled()) {
                callback.onLayoutCancelled();
                return;
            }
            PrintDocumentInfo info = new PrintDocumentInfo.Builder(jobName + ".pdf")
                    .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT)
                    .setPageCount(PrintDocumentInfo.PAGE_COUNT_UNKNOWN)
                    .build();
            callback.onLayoutFinished(info, true);
        }

        @Override
        public void onWrite(PageRange[] pages,
                            ParcelFileDescriptor destination,
                            CancellationSignal cancellationSignal,
                            WriteResultCallback callback) {
            try (InputStream in = new FileInputStream(source);
                 OutputStream out = new FileOutputStream(destination.getFileDescriptor())) {
                byte[] buf = new byte[16 * 1024];
                int read;
                while ((read = in.read(buf)) > 0) {
                    if (cancellationSignal.isCanceled()) {
                        callback.onWriteCancelled();
                        return;
                    }
                    out.write(buf, 0, read);
                }
                callback.onWriteFinished(new PageRange[]{PageRange.ALL_PAGES});
            } catch (IOException e) {
                callback.onWriteFailed(e.getMessage());
            }
        }

        @Override
        public void onFinish() {
            super.onFinish();
            if (source != null && source.exists()) {
                //noinspection ResultOfMethodCallIgnored
                source.delete();
            }
        }
    }
}
