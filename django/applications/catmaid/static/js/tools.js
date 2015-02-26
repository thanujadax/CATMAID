/* -*- mode: espresso; espresso-indent-level: 2; indent-tabs-mode: nil -*- */
/* vim: set softtabstop=2 shiftwidth=2 tabstop=2 expandtab: */

// Namespace declaration
CATMAID.tools = CATMAID.tools || {};

/**
 * Definition of methods in CATMAID.tools namespace.
 */
(function(tools) {

  "use strict";

  /**
   * Does a simple user agent test and returns one of 'MAC', 'WIN', 'LINUX' or
   * 'UNKNOWN'.
   */
  tools.getOS = function()
  {
    var ua = navigator.userAgent.toUpperCase();
    if (-1 !== ua.indexOf('MAC')) {
      return 'MAC';
    } else if (-1 !== ua.indexOf('WIN')) {
      return 'WIN';
    } else if (-1 !== ua.indexOf('LINUX')) {
      return 'LINUX';
    } else {
      return 'UNKNOWN';
    }
  };

  /**
   * Compare two strings while respecting locales and numbers. This is
   * essentially a wrapper around String.localeCompare() to have one
   * place where it is parameterized.
   */
  tools.compareStrings = function(str1, str2)
  {
    return str1.localeCompare(str2, undefined, {numeric: true});
  };

  /**
   * Parse a string as integer or return false if this is not possible or the
   * integer is negative.
   */
  tools.parseIndex = function(str) {
    var pattern = /(\d+)$/;
    if (pattern.test(str)) return parseInt(RegExp.$1);
    else
    return false;
  };

  /**
   * Get a "unique" id for a new element in the DOM.
   */
  var UNIQUE_ID;
  tools.uniqueId = function() {
    if (!UNIQUE_ID) {
      UNIQUE_ID = Math.floor(1073741824 * Math.random());
    }
    return ++UNIQUE_ID;
  };

  /**
   * Parse the query part of a URL and return an object containing all the GET
   * properties.
   */
  tools.parseQuery = function(url) {
    if (url) {
      var r, query;
      query = /\?(.*?)$/i;
      var r = query.exec(url);
      if (r) {
        var o, p, value;
        o = {};
        value = /([^&=]+)=([^&=]+)/gi;
        while ((p = value.exec(r[1])) !== null) {
          o[p[1]] = p[2];
        }
        return o;
      } else
      return undefined;
    } else
    return undefined;
  };

  /**
   * Simplify more robust prototype inheritance. From:
   * http://michaux.ca/articles/class-based-inheritance-in-javascript
   */
  tools.extend = function(subclass, superclass) {
     function Dummy() {}
     Dummy.prototype = superclass.prototype;
     subclass.prototype = new Dummy();
     subclass.prototype.constructor = subclass;
     subclass.superclass = superclass;
     subclass.superproto = superclass.prototype;
  };

  /**
   * Creates a deep copy of an object. Based on:
   * http://stackoverflow.com/questions/122102
   */
  tools.deepCopy = function(obj) {
      if(obj === null || typeof(obj) !== 'object'){
          return obj;
      }
      //make sure the returned object has the same prototype as the original
      var ret = Object.create(Object.getPrototypeOf(obj));
      for(var key in obj){
          ret[key] = tools.deepCopy(obj[key]);
      }
      return ret;
  };

  /**
   * Convert a (usually base64 encorded) dataURI image to a binary blob.
   * From: http://stackoverflow.com/questions/4998908
   */
  tools.dataURItoBlob = function(dataURI) {
      // convert base64/URLEncoded data component to raw binary data held in a string
      var byteString;
      if (dataURI.split(',')[0].indexOf('base64') >= 0)
          byteString = atob(dataURI.split(',')[1]);
      else
          byteString = unescape(dataURI.split(',')[1]);

      // separate out the mime component
      var mimeString = dataURI.split(',')[0].split(':')[1].split(';')[0];

      // write the bytes of the string to a typed array
      var ia = new Uint8Array(byteString.length);
      for (var i = 0; i < byteString.length; i++) {
          ia[i] = byteString.charCodeAt(i);
      }

      return new Blob([ia], {type:mimeString});
  };

  /**
   * Return the intersection of the line given by the two points with the XY plane
   * through the given Z.
   */
  tools.intersectLineWithZPlane = function(x1, y1, z1, x2, y2, z2, zPlane)
  {
    // General point equation would be P1 + (P2 - P1) * t, calculate d = P2 - P1
    var dx = x2 - x1;
    var dy = y2 - y1;
    var dz = z2 - z1;

    // Now the correct t needs to be found that intersects the given z plane.
    // Using the general point equation we can determine z = z1 + dz * t, which
    // translates to t = (z - z1) / dz. With z being our z plane we get the
    // correct t where the intersection happens.
    var t = (zPlane - z1) / dz;

    // Return the intersection X and Y by using the general point equation. Z
    // was already given as a parameter.

    return [x1 + t * dx, y1 + t * dy];
  };

})(CATMAID.tools);
