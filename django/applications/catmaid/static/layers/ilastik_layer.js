/* -*- mode: espresso; espresso-indent-level: 2; indent-tabs-mode: nil -*- */
/* vim: set softtabstop=2 shiftwidth=2 tabstop=2 expandtab: */

function IlastikDataLayer(stack, data)
{
  this.stack = stack;
  this.data = data;
  this.opacity = 1;
  this.radius = 3;

  // Create container, aligned to the upper left
  this.view = document.createElement("div");
  this.view.style.position = "absolute";
  this.view.style.left = 0;
  this.view.style.top = 0;

  // Append it to DOM
  stack.getView().appendChild(this.view);

  // Create SVG
  this.paper = Raphael(this.view,
      Math.floor(stack.dimension.x * stack.scale),
      Math.floor(stack.dimension.y * stack.scale));
};

IlastikDataLayer.prototype = {};

IlastikDataLayer.prototype.getLayerName = function()
{
  return "Ilastik data";
};

IlastikDataLayer.prototype.setOpacity = function( val )
{
    this.view.style.opacity = val;
    this.opacity = val;
};

IlastikDataLayer.prototype.getOpacity = function()
{
    return this.opacity;
};

IlastikDataLayer.prototype.resize = function()
{
  this.redraw();
};

IlastikDataLayer.prototype.redraw = function(completionCallback)
{
  // Get view box in local/stack and world/project coordinates
  var localViewBox = this.stack.createStackViewBox();
  var worldViewBox = this.stack.createStackToProjectBox(localViewBox);

  // Find data points on current slice
  var z = this.stack.z;
  var stackPositions = this.data.filter(function(p) {
    return p[3] == z; 
  });

  // Translate the stack positions found to screen space
  // TODO: Expect project coordinates to handle different stacks
  // TODO: Handle orthogonal views
  var screenPositions = stackPositions.map((function(p) {
    var s = this.stack;
    return [
      (p[1] - s.x) * s.scale + s.viewWidth * 0.5,
      (p[2] - s.y) * s.scale + s.viewHeight * 0.5
    ];
  }).bind(this));

  // Clean paper
  this.paper.clear();
  screenPositions.forEach((function(p) {
    var circle = this.paper.circle(p[0], p[1], this.radius);
    circle.attr('fill', '#00f');
    circle.attr('stroke', '#0ff');
  }).bind(this));

  if (completionCallback) {
      completionCallback();
  }
};

IlastikDataLayer.prototype.unregister = function()
{
  this.stack.getView().removeChild(this.view);
};